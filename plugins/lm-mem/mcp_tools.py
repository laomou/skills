"""lm-mem MCP 工具层:FastMCP + 14 个 @mcp.tool()。

依赖 memory_utils 与 backend。不依赖 web。

## 返回值约定(MCP-native)

- **成功**:直接返回业务数据的 JSON 字符串,不包 `{ok, ...}` envelope
- **失败**:抛异常,MCP 协议层自动包装成 `isError: true` 返回给 LLM
- **业务分支**(如 add_memory 查重命中):返回带业务标识字段的 JSON(如 `duplicate_id`),不是错误

时间戳统一 Unix 秒(float),前端负责格式化。
"""
from __future__ import annotations

import csv
import io
import json
import os
import time
import uuid

from mcp.server.fastmcp import FastMCP

from backend import _collection
from memory_utils import (
    _clauses,
    _coerce_scalar,
    _combine,
    _DEDUP_THRESHOLD,
    _hits_to_records,
    _is_expired,
    _MD_PREFIX,
    _memory_to_record,
    _messages_to_text,
    _metadata_filter_clauses,
    _OVERFETCH,
    _parse_metadata,
    _scope_meta,
    _SCOPE_KEYS,
    _scope_where,
    _user_metadata,
)

mcp = FastMCP("lm-mem")


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


def _check_duplicate(text, scope_clauses):
    """查同作用域内是否有相似度 ≥0.85 的记忆。返回业务分支 JSON(命中时)或 None。"""
    res = _collection.query(
        query_texts=[text],
        n_results=1,
        where=_combine(scope_clauses),
    )
    if not res["ids"] or not res["ids"][0]:
        return None
    dist = res["distances"][0][0]
    sim = 1 - dist
    if sim < _DEDUP_THRESHOLD or _is_expired(res["metadatas"][0][0]):
        return None
    dup_id = res["ids"][0][0]
    dup_doc = res["documents"][0][0]
    return _dumps({
        "duplicate_id": dup_id,
        "similarity": round(sim, 3),
        "existing_content": dup_doc,
        "hint": (
            f"疑似重复(相似度 {sim:.2f}),未插入。"
            "内容有变化 → update_memory(该 id, 新内容);"
            "已足够 → 跳过;确需新增 → add_memory(..., force=True)。"
        ),
    })


def _persist_memory(text, user_id, agent_id, app_id, run_id, tags, metadata, ttl_seconds):
    """写入一条记忆,返回 mem_id。"""
    mem_id = str(uuid.uuid4())
    now = time.time()
    meta = {"created_at": now, "tags": tags.strip()}
    meta.update(_scope_meta(user_id, agent_id, app_id, run_id))
    meta.update(_parse_metadata(metadata))
    if ttl_seconds and ttl_seconds > 0:
        meta["expires_at"] = now + ttl_seconds
    _collection.add(ids=[mem_id], documents=[text], metadatas=[meta])
    return mem_id


@mcp.tool()
def add_memory(
    content: str = "",
    messages: str = "",
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
    tags: str = "",
    metadata: str = "",
    ttl_seconds: int = 0,
    force: bool = False,
) -> str:
    """保存一条记忆(可绑定作用域、自定义元数据、过期时间)。

    输入(二选一):
        content: 要记住的文本。
        messages: 对话历史(JSON 数组,如 '[{"role":"user","content":"..."}]'),
                  未提供 content 时会自动拼成文本存储。

    Args:
        user_id / agent_id / app_id / run_id: 可选,记忆归属的实体(可多个)。
        tags: 可选,逗号分隔的标签。
        metadata: 可选,JSON 对象字符串,附加 category/importance/source 等自定义字段。
        ttl_seconds: 可选,>0 时记忆在该秒数后过期(检索自动忽略,可用 purge_expired 清理)。
        force: 默认 False。为 False 时,若同作用域内已有高度相似记忆,则不插入、
               直接返回疑似重复项交由调用方决策(更新/跳过/强制新增)。

    Returns:
        成功:`{"id": "..."}`
        查重命中:`{"duplicate_id": "...", "similarity": 0.95, "existing_content": "...", "hint": "..."}`
    Raises:
        ValueError: content 与 messages 均为空。
    """
    text = content.strip() if content else ""
    if not text and messages:
        text = _messages_to_text(messages)
    if not text:
        raise ValueError("content 与 messages 均为空,没有可保存的内容。")

    scope_clauses = _clauses(user_id, agent_id, app_id, run_id)
    if not force:
        if dup := _check_duplicate(text, scope_clauses):
            return dup

    mem_id = _persist_memory(text, user_id, agent_id, app_id, run_id,
                             tags, metadata, ttl_seconds)
    return _dumps({"id": mem_id})


@mcp.tool()
def search_memories(
    query: str,
    limit: int = 5,
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
    metadata_filter: str = "",
) -> str:
    """按语义相似度检索记忆,可用作用域 / 自定义元数据过滤。

    Args:
        query: 检索问题/关键词(自然语言)。
        limit: 返回的最大条数,默认 5。
        user_id / agent_id / app_id / run_id: 可选,限定检索范围。
        metadata_filter: 可选,JSON 对象字符串,按自定义 metadata 精确过滤
                         (如 '{"category":"pref"}')。

    Returns:
        `{"items": [{id, content, similarity, scope, metadata, ...}]}`
    """
    clauses = _clauses(user_id, agent_id, app_id, run_id)
    clauses += _metadata_filter_clauses(metadata_filter)
    where = _combine(clauses)

    n = max(limit * _OVERFETCH, limit + 10, 100)
    res = _collection.query(query_texts=[query], n_results=n, where=where)
    items = _hits_to_records(res, limit)
    return _dumps({"items": items})


@mcp.tool()
def get_memories(
    limit: int = 50,
    offset: int = 0,
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
    metadata_filter: str = "",
) -> str:
    """列出记忆,支持作用域 / 元数据过滤与分页。

    Args:
        limit: 每页条数,默认 50。
        offset: 偏移量,用于翻页,默认 0。
        user_id / agent_id / app_id / run_id: 可选,限定范围。
        metadata_filter: 可选,JSON 对象字符串,按自定义 metadata 过滤。

    Returns:
        `{"items": [...], "offset": 0}`
    """
    clauses = _clauses(user_id, agent_id, app_id, run_id)
    clauses += _metadata_filter_clauses(metadata_filter)
    where = _combine(clauses)
    res = _collection.get(
        where=where, limit=limit, offset=offset, include=["documents", "metadatas"]
    )
    now = time.time()
    items = [
        _memory_to_record(mem_id, doc, meta)
        for mem_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"])
        if not _is_expired(meta, now)
    ]
    return _dumps({"items": items, "offset": offset})


@mcp.tool()
def get_memory(mem_id: str) -> str:
    """按 id 获取单条记忆。

    Returns:
        `{"id": ..., "content": ..., ...}` — 单条记忆的完整字段
    Raises:
        ValueError: 未找到 mem_id。
    """
    res = _collection.get(ids=[mem_id], include=["documents", "metadatas"])
    if not res["ids"]:
        raise ValueError(f"未找到 id={mem_id} 的记忆。")
    return _dumps(_memory_to_record(res["ids"][0], res["documents"][0], res["metadatas"][0]))


@mcp.tool()
def update_memory(
    mem_id: str,
    content: str = "",
    metadata: str = "",
    tags: str = "",
    ttl_seconds: int = 0,
) -> str:
    """按 id 更新记忆(保留原作用域;可同时改文本/元数据/标签/过期时间)。

    Args:
        mem_id: 记忆 id。
        content: 可选,新的文本内容(留空则不改文本)。
        metadata: 可选,JSON 对象字符串,合并进现有自定义元数据。
        tags: 可选,新的逗号分隔标签(留空则不改)。
        ttl_seconds: 可选。>0 从现在起续期该秒数;<0 立即清除过期时间(转为永久);
                     0(默认)不改动过期设置。

    Returns:
        `{"id": mem_id}`
    Raises:
        ValueError: 未找到 mem_id。
    """
    existing = _collection.get(ids=[mem_id], include=["documents", "metadatas"])
    if not existing["ids"]:
        raise ValueError(f"未找到 id={mem_id} 的记忆。")
    meta = existing["metadatas"][0] or {}
    now = time.time()
    meta["updated_at"] = now
    if tags:
        meta["tags"] = tags.strip()
    if metadata:
        meta.update(_parse_metadata(metadata))
    if ttl_seconds > 0:
        meta["expires_at"] = now + ttl_seconds
    elif ttl_seconds < 0:
        meta["expires_at"] = 0
    doc = content.strip() if content else existing["documents"][0]
    _collection.update(ids=[mem_id], documents=[doc], metadatas=[meta])
    return _dumps({"id": mem_id})


@mcp.tool()
def delete_memory(mem_id: str) -> str:
    """按 id 删除单条记忆。

    Returns:
        `{"id": mem_id}`
    Raises:
        ValueError: 未找到 mem_id。
    """
    if not _collection.get(ids=[mem_id])["ids"]:
        raise ValueError(f"未找到 id={mem_id} 的记忆。")
    _collection.delete(ids=[mem_id])
    return _dumps({"id": mem_id})


@mcp.tool()
def delete_all_memories(
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
) -> str:
    """批量删除作用域内的所有记忆。

    安全约束:必须至少提供一个作用域(user/agent/app/run),
    以避免误删整个记忆库。

    Returns:
        `{"deleted": N}` — 实际删除数量(0 表示该作用域内本就没记忆)
    Raises:
        ValueError: 未指定任何作用域。
    """
    where = _scope_where(user_id, agent_id, app_id, run_id)
    if where is None:
        raise ValueError("必须指定至少一个作用域(user_id/agent_id/app_id/run_id)。")
    hits = _collection.get(where=where)
    n = len(hits["ids"])
    if n > 0:
        _collection.delete(where=where)
    return _dumps({"deleted": n})


@mcp.tool()
def delete_entities(entity_type: str, entity_id: str) -> str:
    """删除某个实体及其所有记忆。

    Args:
        entity_type: 实体类型,取值 user / agent / app / run。
        entity_id: 实体标识。

    Returns:
        `{"deleted": N}`
    Raises:
        ValueError: entity_type 非法,或未找到实体。
    """
    key = f"{entity_type}_id"
    if key not in _SCOPE_KEYS:
        raise ValueError(f"无效的 entity_type={entity_type}(应为 user/agent/app/run)。")
    hits = _collection.get(where={key: entity_id})
    if not hits["ids"]:
        raise ValueError(f"未找到 {entity_type}={entity_id} 的记忆。")
    n = len(hits["ids"])
    _collection.delete(where={key: entity_id})
    return _dumps({"deleted": n})


@mcp.tool()
def list_entities(entity_type: str = "") -> str:
    """列出已存储的实体(users/agents/apps/runs)。

    Args:
        entity_type: 可选,只列某一类(user/agent/app/run);留空则全部。

    Returns:
        `{"entities": {"user_id": [...], "agent_id": [...], ...}}` — 统一按类型分组
    Raises:
        ValueError: entity_type 非法。
    """
    res = _collection.get(include=["metadatas"])
    buckets = {k: set() for k in _SCOPE_KEYS}
    for meta in res["metadatas"]:
        for key in _SCOPE_KEYS:
            if meta and meta.get(key):
                buckets[key].add(meta[key])

    if entity_type:
        key = f"{entity_type}_id"
        if key not in _SCOPE_KEYS:
            raise ValueError(f"无效的 entity_type={entity_type}。")
        return _dumps({"entities": {key: sorted(buckets[key])}})

    return _dumps({"entities": {k: sorted(buckets[k]) for k in _SCOPE_KEYS}})


@mcp.tool()
def memory_stats(
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
) -> str:
    """统计记忆库:总数、按作用域/标签/自定义分类聚合、过期数量。

    Args:
        user_id / agent_id / app_id / run_id: 可选,只统计某作用域。

    Returns:
        `{"counts": {"total", "active", "expired"}, "scope": {...}, "tags": {...}, "categories": {...}}`
    """
    where = _scope_where(user_id, agent_id, app_id, run_id)
    res = _collection.get(where=where, include=["metadatas"])
    metas = res["metadatas"]
    total = len(res["ids"])
    now = time.time()
    expired = sum(1 for m in metas if _is_expired(m, now))
    active = total - expired
    scope_counts = {k: {} for k in _SCOPE_KEYS}
    tag_counts = {}
    category_counts = {}
    for m in metas:
        m = m or {}
        if _is_expired(m, now):
            continue
        for key in _SCOPE_KEYS:
            if m.get(key):
                scope_counts[key][m[key]] = scope_counts[key].get(m[key], 0) + 1
        for t in (m.get("tags") or "").split(","):
            t = t.strip()
            if t:
                tag_counts[t] = tag_counts.get(t, 0) + 1
        cat = m.get(f"{_MD_PREFIX}category")
        if cat is not None:
            category_counts[cat] = category_counts.get(cat, 0) + 1

    return _dumps({
        "counts": {"total": total, "active": active, "expired": expired},
        "scope": scope_counts,
        "tags": tag_counts,
        "categories": category_counts,
    })


@mcp.tool()
def export_memories(
    fmt: str = "json",
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
) -> str:
    """批量导出记忆为 JSON 或 CSV 文本。

    Args:
        fmt: 导出格式,json(默认)或 csv。
        user_id / agent_id / app_id / run_id: 可选,只导出某作用域。

    Returns:
        fmt=json: `{"records": [...]}`
        fmt=csv:  `{"csv": "..."}`
    Raises:
        ValueError: fmt 非法。
    """
    fmt = fmt.lower().strip()
    if fmt not in ("json", "csv"):
        raise ValueError(f"无效的 fmt={fmt}(应为 json 或 csv)。")
    where = _scope_where(user_id, agent_id, app_id, run_id)
    res = _collection.get(where=where, include=["documents", "metadatas"])

    records = []
    for mem_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"]):
        meta = meta or {}
        rec = {
            "id": mem_id,
            "content": doc,
            "tags": meta.get("tags", ""),
            "created_at": meta.get("created_at"),
            "updated_at": meta.get("updated_at"),
            "expires_at": meta.get("expires_at"),
        }
        for key in _SCOPE_KEYS:
            if meta.get(key):
                rec[key] = meta[key]
        rec["metadata"] = _user_metadata(meta)
        records.append(rec)

    if fmt == "json":
        return _dumps({"records": records})

    buf = io.StringIO()
    fields = ["id", "content", "tags", "created_at", "updated_at", "expires_at"]
    fields += list(_SCOPE_KEYS) + ["metadata"]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for rec in records:
        row = dict(rec)
        row["metadata"] = json.dumps(rec["metadata"], ensure_ascii=False)
        writer.writerow(row)
    return _dumps({"csv": buf.getvalue()})


@mcp.tool()
def purge_expired() -> str:
    """清理所有已过期(超过 TTL)的记忆。

    Returns:
        `{"deleted": N}`
    """
    res = _collection.get(include=["metadatas"])
    now = time.time()
    expired_ids = [
        mem_id
        for mem_id, meta in zip(res["ids"], res["metadatas"])
        if _is_expired(meta, now)
    ]
    if expired_ids:
        _collection.delete(ids=expired_ids)
    return _dumps({"deleted": len(expired_ids)})


@mcp.tool()
def get_user_context(
    user_id: str = "",
    limit: int = 10,
) -> str:
    """获取用户的核心上下文:偏好、身份、环境等长期属性。

    LLM 应在**新会话第一轮涉及代码/行为决策时**主动调用一次,把结果吃进上下文,
    避免后续每轮都要 search_memories。返回结果按 importance:high 优先。

    Args:
        user_id: 可选,限定用户(推荐传入,以免拿到别人的偏好)。
        limit: 返回条数上限,默认 10。

    Returns:
        `{"items": [{id, content, category, importance, ...}]}` — 按 importance 排序。
    """
    where_scope = _scope_where(user_id, "", "", "")
    # 过滤:category ∈ {preference, identity, environment} —— 长期属性
    # ChromaDB where 只支持 AND 精确匹配,所以我们分别查三次再合并
    core_categories = ("preference", "identity", "environment")
    now = time.time()
    all_hits = []
    seen_ids = set()
    for cat in core_categories:
        cat_clauses = []
        if where_scope is not None:
            # where_scope 可能是单 dict 或 {$and:[...]}, 都转成 clauses 列表
            if "$and" in where_scope:
                cat_clauses.extend(where_scope["$and"])
            else:
                cat_clauses.append(where_scope)
        cat_clauses.append({f"{_MD_PREFIX}category": cat})
        where = _combine(cat_clauses)
        res = _collection.get(where=where, include=["documents", "metadatas"])
        for mem_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"]):
            if mem_id in seen_ids or _is_expired(meta, now):
                continue
            seen_ids.add(mem_id)
            all_hits.append((mem_id, doc, meta or {}))

    # 按 importance 排序(high > medium > low > 缺失),然后 created_at 倒序
    importance_rank = {"high": 3, "medium": 2, "low": 1}
    all_hits.sort(
        key=lambda x: (
            -importance_rank.get(x[2].get(f"{_MD_PREFIX}importance", ""), 0),
            -(x[2].get("created_at") or 0),
        )
    )
    items = [_memory_to_record(mid, doc, meta) for mid, doc, meta in all_hits[:limit]]
    return _dumps({"items": items})


@mcp.tool()
def import_memories(
    data: str,
    fmt: str = "json",
    overwrite: bool = False,
    new_ids: bool = False,
) -> str:
    """从导出数据批量导入记忆(对称 export_memories)。

    Args:
        data: JSON 数组字符串(fmt=json,与 export.records 同构) 或 CSV 字符串(fmt=csv,含 header)。
        fmt: 'json' 或 'csv',默认 json。
        overwrite: 遇到重复 id 时是否覆盖(默认 False,重复 id 会被 skip)。
        new_ids: 是否为每条生成新 uuid(默认 False 保留原 id)。overwrite 与 new_ids 互斥。

    Returns:
        `{"imported": N, "skipped": N, "overwritten": N}`
    Raises:
        ValueError: fmt 非法 / data 解析失败 / overwrite 与 new_ids 同时为 True。
    """
    fmt = fmt.lower().strip()
    if fmt not in ("json", "csv"):
        raise ValueError(f"无效的 fmt={fmt}(应为 json 或 csv)。")
    if overwrite and new_ids:
        raise ValueError("overwrite 与 new_ids 互斥。")

    if fmt == "json":
        try:
            records = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"data 不是合法 JSON:{exc}") from exc
        if not isinstance(records, list):
            raise ValueError("data 必须是 JSON 数组。")
    else:
        try:
            reader = csv.DictReader(io.StringIO(data))
            records = list(reader)
        except Exception as exc:
            raise ValueError(f"data 不是合法 CSV:{exc}") from exc

    imported, skipped, overwritten = 0, 0, 0
    for rec in records:
        if not isinstance(rec, dict):
            skipped += 1
            continue
        text = (rec.get("content") or "").strip()
        if not text:
            skipped += 1
            continue

        # id 处理
        orig_id = rec.get("id", "")
        mem_id = str(uuid.uuid4()) if new_ids or not orig_id else orig_id
        exists = bool(_collection.get(ids=[mem_id])["ids"]) if orig_id else False
        if exists and not overwrite:
            skipped += 1
            continue

        # 构造 metadata
        meta = {}
        # 保留原时间戳,否则用当前
        meta["created_at"] = _to_float(rec.get("created_at")) or time.time()
        if updated := _to_float(rec.get("updated_at")):
            meta["updated_at"] = updated
        if expires := _to_float(rec.get("expires_at")):
            meta["expires_at"] = expires
        # tags
        tags = rec.get("tags", "")
        if isinstance(tags, list):
            tags = ",".join(str(t) for t in tags)
        meta["tags"] = str(tags).strip()
        # scope
        for key in _SCOPE_KEYS:
            if val := rec.get(key):
                meta[key] = val
        # 用户 metadata(CSV 里 metadata 是 JSON 字符串,JSON 里是 dict)
        user_md = rec.get("metadata")
        if isinstance(user_md, str) and user_md:
            try:
                user_md = json.loads(user_md)
            except json.JSONDecodeError:
                user_md = {}
        if isinstance(user_md, dict):
            for k, v in user_md.items():
                meta[f"{_MD_PREFIX}{k}"] = _coerce_scalar(v)

        if exists:
            _collection.update(ids=[mem_id], documents=[text], metadatas=[meta])
            overwritten += 1
        else:
            _collection.add(ids=[mem_id], documents=[text], metadatas=[meta])
            imported += 1

    return _dumps({"imported": imported, "skipped": skipped, "overwritten": overwritten})


def _to_float(v):
    """尝试把 CSV/JSON 里的时间戳转 float,失败返回 None。"""
    if v in (None, "", "null"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
