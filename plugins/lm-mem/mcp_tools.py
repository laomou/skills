"""lm-mem MCP 工具层:FastMCP + 13 个 @mcp.tool()。

依赖 helpers 与 db。不依赖 web。
"""
from __future__ import annotations

import csv
import io
import json
import os
import time
import uuid

from mcp.server.fastmcp import FastMCP

from db import _collection
from helpers import (
    _clauses,
    _combine,
    _DEDUP_THRESHOLD,
    _fmt,
    _is_expired,
    _MD_PREFIX,
    _messages_to_text,
    _metadata_filter_clauses,
    _OVERFETCH,
    _parse_metadata,
    _render_hits,
    _scope_meta,
    _SCOPE_KEYS,
    _scope_where,
    _user_metadata,
)

mcp = FastMCP("lm-mem")


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
        新记忆的 id;或疑似重复的提示。
    """
    text = content.strip() if content else ""
    if not text and messages:
        text = _messages_to_text(messages)
    if not text:
        return "拒绝执行:content 与 messages 均为空,没有可保存的内容。"

    scope_clauses = _clauses(user_id, agent_id, app_id, run_id)

    if not force and _collection.count() > 0:
        res = _collection.query(
            query_texts=[text],
            n_results=1,
            where=_combine(scope_clauses),
        )
        if res["ids"] and res["ids"][0]:
            dist = res["distances"][0][0]
            sim = 1 - dist
            if sim >= _DEDUP_THRESHOLD and not _is_expired(res["metadatas"][0][0]):
                dup_id = res["ids"][0][0]
                dup_doc = res["documents"][0][0]
                return (
                    f"疑似重复(相似度 {sim:.2f}),未插入。已有记忆:\n"
                    f"  id={dup_id}\n  内容: {dup_doc}\n"
                    f"请决策:内容有变化 -> update_memory(该 id, 新内容);"
                    f"已足够 -> 跳过;确需新增 -> add_memory(..., force=True)。"
                )

    mem_id = str(uuid.uuid4())
    now = time.time()
    meta = {"created_at": now, "tags": tags.strip()}
    meta.update(_scope_meta(user_id, agent_id, app_id, run_id))
    meta.update(_parse_metadata(metadata))
    if ttl_seconds and ttl_seconds > 0:
        meta["expires_at"] = now + ttl_seconds
    _collection.add(ids=[mem_id], documents=[text], metadatas=[meta])
    return f"已保存记忆 id={mem_id}"


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
                         (如 '{"category":"pref"})。
    """
    if _collection.count() == 0:
        return "记忆库为空。"

    clauses = _clauses(user_id, agent_id, app_id, run_id)
    clauses += _metadata_filter_clauses(metadata_filter)
    where = _combine(clauses)

    total = _collection.count()
    n = min(total, max(limit * _OVERFETCH, limit + 10))
    res = _collection.query(query_texts=[query], n_results=n, where=where)
    lines = _render_hits(res, limit)
    if len(lines) < limit and n < total:
        res = _collection.query(query_texts=[query], n_results=total, where=where)
        lines = _render_hits(res, limit)
    if not lines:
        return "没有匹配的记忆。"
    return "\n\n".join(lines)


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
    """
    clauses = _clauses(user_id, agent_id, app_id, run_id)
    clauses += _metadata_filter_clauses(metadata_filter)
    where = _combine(clauses)
    res = _collection.get(
        where=where, limit=limit, offset=offset, include=["documents", "metadatas"]
    )
    if not res["ids"]:
        return "没有匹配的记忆。"

    now = time.time()
    lines = [
        _fmt(mem_id, doc, meta)
        for mem_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"])
        if not _is_expired(meta, now)
    ]
    if not lines:
        return "没有匹配的记忆。"
    return f"返回 {len(lines)} 条(offset={offset}):\n\n" + "\n\n".join(lines)


@mcp.tool()
def get_memory(mem_id: str) -> str:
    """按 id 获取单条记忆。"""
    res = _collection.get(ids=[mem_id], include=["documents", "metadatas"])
    if not res["ids"]:
        return f"未找到 id={mem_id} 的记忆。"
    return _fmt(res["ids"][0], res["documents"][0], res["metadatas"][0])


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
    """
    existing = _collection.get(ids=[mem_id], include=["documents", "metadatas"])
    if not existing["ids"]:
        return f"未找到 id={mem_id} 的记忆。"
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
    return f"已更新 id={mem_id}"


@mcp.tool()
def delete_memory(mem_id: str) -> str:
    """按 id 删除单条记忆。"""
    if not _collection.get(ids=[mem_id])["ids"]:
        return f"未找到 id={mem_id} 的记忆。"
    _collection.delete(ids=[mem_id])
    return f"已删除 id={mem_id}"


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
    """
    where = _scope_where(user_id, agent_id, app_id, run_id)
    if where is None:
        return "拒绝执行:必须指定至少一个作用域(user_id/agent_id/app_id/run_id)。"
    hits = _collection.get(where=where)
    if not hits["ids"]:
        return "该作用域内没有记忆。"
    _collection.delete(where=where)
    return f"已删除 {len(hits['ids'])} 条记忆。"


@mcp.tool()
def delete_entities(entity_type: str, entity_id: str) -> str:
    """删除某个实体及其所有记忆。

    Args:
        entity_type: 实体类型,取值 user / agent / app / run。
        entity_id: 实体标识。
    """
    key = f"{entity_type}_id"
    if key not in _SCOPE_KEYS:
        return f"无效的 entity_type={entity_type}(应为 user/agent/app/run)。"
    hits = _collection.get(where={key: entity_id})
    if not hits["ids"]:
        return f"未找到 {entity_type}={entity_id} 的记忆。"
    _collection.delete(where={key: entity_id})
    return f"已删除实体 {entity_type}={entity_id} 及其 {len(hits['ids'])} 条记忆。"


@mcp.tool()
def list_entities(entity_type: str = "") -> str:
    """列出已存储的实体(users/agents/apps/runs)。

    Args:
        entity_type: 可选,只列某一类(user/agent/app/run);留空则全部。
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
            return f"无效的 entity_type={entity_type}。"
        vals = sorted(buckets[key])
        return f"{entity_type}: {', '.join(vals) if vals else '(无)'}"

    lines = []
    for key in _SCOPE_KEYS:
        vals = sorted(buckets[key])
        lines.append(f"{key[:-3]}: {', '.join(vals) if vals else '(无)'}")
    return "\n".join(lines)


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
    """
    where = _scope_where(user_id, agent_id, app_id, run_id)
    res = _collection.get(where=where, include=["metadatas"])
    metas = res["metadatas"]
    total = len(res["ids"])
    if total == 0:
        return "记忆库为空(在该作用域内)。"

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

    lines = [f"有效记忆数: {active}", f"已过期(待清理): {expired}", f"总计: {total}"]
    for key in _SCOPE_KEYS:
        if scope_counts[key]:
            inner = ", ".join(f"{k}={v}" for k, v in sorted(scope_counts[key].items()))
            lines.append(f"{key}: {inner}")
    if tag_counts:
        inner = ", ".join(f"{k}={v}" for k, v in sorted(tag_counts.items()))
        lines.append(f"标签: {inner}")
    if category_counts:
        inner = ", ".join(f"{k}={v}" for k, v in sorted(category_counts.items()))
        lines.append(f"分类(metadata.category): {inner}")
    return "\n".join(lines)


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
    """
    fmt = fmt.lower().strip()
    if fmt not in ("json", "csv"):
        return f"无效的 fmt={fmt}(应为 json 或 csv)。"
    where = _scope_where(user_id, agent_id, app_id, run_id)
    res = _collection.get(where=where, include=["documents", "metadatas"])
    if not res["ids"]:
        return "该作用域内没有记忆。"

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
        return json.dumps(records, ensure_ascii=False, indent=2)

    buf = io.StringIO()
    fields = ["id", "content", "tags", "created_at", "updated_at", "expires_at"]
    fields += list(_SCOPE_KEYS) + ["metadata"]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for rec in records:
        row = dict(rec)
        row["metadata"] = json.dumps(rec["metadata"], ensure_ascii=False)
        writer.writerow(row)
    return buf.getvalue()


@mcp.tool()
def purge_expired() -> str:
    """清理所有已过期(超过 TTL)的记忆。"""
    res = _collection.get(include=["metadatas"])
    now = time.time()
    expired_ids = [
        mem_id
        for mem_id, meta in zip(res["ids"], res["metadatas"])
        if _is_expired(meta, now)
    ]
    if not expired_ids:
        return "没有已过期的记忆。"
    _collection.delete(ids=expired_ids)
    return f"已清理 {len(expired_ids)} 条过期记忆。"


# 开箱即带 Web 记忆台
# 由环境变量 LM_MEM_WEB(默认 on)控制,设 0/off 时禁用。
# Web 台用后台 daemon 线程 + 端口抢占保证全局单例,和 Chroma 后端一样。
if os.environ.get("LM_MEM_WEB", "on").strip().lower() not in ("0", "off", "no", "false"):
    try:
        from web import start_web_thread  # noqa: F811
    except ImportError:
        pass
    else:
        start_web_thread()
