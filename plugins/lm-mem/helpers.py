"""lm-mem 纯函数层:作用域、元数据、格式化等工具函数。

零运行时依赖(chromadb/FastMCP),只依赖 Python 标准库。
"""
from __future__ import annotations

import json
import time

# 作用域字段:归属实体的维度。
_SCOPE_KEYS = ("user_id", "agent_id", "app_id", "run_id")
# 内部保留的 metadata 键(不属于用户自定义 metadata)。
_RESERVED_KEYS = _SCOPE_KEYS + ("created_at", "updated_at", "tags", "expires_at")
# 用户自定义 metadata 的键前缀,避免与保留键冲突。
_MD_PREFIX = "m:"
# 添加去重:语义相似度 >= 该阈值视为疑似重复。
_DEDUP_THRESHOLD = 0.85
# 检索时的过取上限:过期项会被过滤掉,故一次多取 limit*_OVERFETCH 条,
# 不够再回退到"取全部候选"补齐,避免过期项挤掉有效结果。
_OVERFETCH = 3


def _scope_meta(user_id, agent_id, app_id, run_id):
    """把作用域参数拼成 metadata(空值不写入,ChromaDB 不接受 None)。"""
    meta = {}
    for key, val in zip(_SCOPE_KEYS, (user_id, agent_id, app_id, run_id)):
        if val:
            meta[key] = val
    return meta


def _clauses(user_id, agent_id, app_id, run_id):
    """作用域参数 -> ChromaDB where 子句列表(每个是单键 dict)。"""
    return [
        {key: val}
        for key, val in zip(_SCOPE_KEYS, (user_id, agent_id, app_id, run_id))
        if val
    ]


def _combine(clauses):
    """把若干单键 where 子句合并成 ChromaDB where(0/1/多 分别处理)。"""
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _scope_where(user_id, agent_id, app_id, run_id):
    return _combine(_clauses(user_id, agent_id, app_id, run_id))


def _coerce_scalar(val):
    """ChromaDB metadata 只接受标量;非标量转 JSON 字符串。"""
    if isinstance(val, (str, int, float, bool)):
        return val
    return json.dumps(val, ensure_ascii=False)


def _parse_metadata(metadata):
    """解析用户传入的 metadata(JSON 对象字符串)-> 扁平 dict(加前缀)。"""
    if not metadata:
        return {}
    if isinstance(metadata, dict):
        obj = metadata
    else:
        try:
            obj = json.loads(metadata)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"metadata 不是合法的 JSON 对象:{exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("metadata 必须是 JSON 对象(键值对)。")
    return {f"{_MD_PREFIX}{k}": _coerce_scalar(v) for k, v in obj.items()}


def _metadata_filter_clauses(metadata_filter):
    """解析 metadata_filter(JSON 对象字符串)-> where 子句列表(加前缀)。"""
    if not metadata_filter:
        return []
    if isinstance(metadata_filter, dict):
        obj = metadata_filter
    else:
        try:
            obj = json.loads(metadata_filter)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"metadata_filter 不是合法 JSON:{exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("metadata_filter 必须是 JSON 对象。")
    return [{f"{_MD_PREFIX}{k}": _coerce_scalar(v)} for k, v in obj.items()]


def _messages_to_text(messages):
    """把对话历史(JSON 数组)拼成可读文本。"""
    if isinstance(messages, str):
        try:
            arr = json.loads(messages)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"messages 不是合法 JSON:{exc}") from exc
    else:
        arr = messages
    if not isinstance(arr, list):
        raise ValueError("messages 必须是 JSON 数组。")
    parts = []
    for m in arr:
        if isinstance(m, dict):
            role = m.get("role", "?")
            content = m.get("content", "")
            parts.append(f"{role}: {content}")
        else:
            parts.append(str(m))
    return "\n".join(parts).strip()


def _user_metadata(meta):
    """从存储的 metadata 里取出用户自定义部分(去前缀)。"""
    return {
        k[len(_MD_PREFIX):]: v
        for k, v in (meta or {}).items()
        if k.startswith(_MD_PREFIX)
    }


def _is_expired(meta, now=None):
    exp = (meta or {}).get("expires_at")
    if not exp:
        return False
    return exp <= (now if now is not None else time.time())


def _to_dict(mem_id, doc, meta):
    """把一条记忆转成结构化 dict(用于 JSON 输出)。"""
    meta = meta or {}
    rec = {
        "id": mem_id,
        "content": doc,
        "tags": meta.get("tags") or "",
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "expires_at": meta.get("expires_at"),
        "scope": {k: meta[k] for k in _SCOPE_KEYS if k in meta},
        "metadata": _user_metadata(meta),
    }
    return rec


def _fmt(mem_id, doc, meta):
    meta = meta or {}
    scope = {k: meta[k] for k in _SCOPE_KEYS if k in meta}
    tags = meta.get("tags") or "-"
    scope_str = json.dumps(scope, ensure_ascii=False) if scope else "-"
    lines = [f"id={mem_id}", f"  内容: {doc}", f"  作用域: {scope_str}", f"  标签: {tags}"]
    user_md = _user_metadata(meta)
    if user_md:
        lines.append(f"  元数据: {json.dumps(user_md, ensure_ascii=False)}")
    if meta.get("expires_at"):
        lines.append(
            f"  过期于: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(meta['expires_at']))}"
        )
    return "\n".join(lines)


def _hits_to_dicts(res, limit, now=None):
    """把 query 结果转成 dict 列表,附带 similarity,跳过过期项,最多 limit 条。"""
    ids = res["ids"][0] if res["ids"] else []
    if not ids:
        return []
    now = now if now is not None else time.time()
    out = []
    for mem_id, doc, meta, dist in zip(
        ids, res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        if _is_expired(meta, now):
            continue
        rec = _to_dict(mem_id, doc, meta)
        rec["similarity"] = round(1 - dist, 3)
        out.append(rec)
        if len(out) >= limit:
            break
    return out
