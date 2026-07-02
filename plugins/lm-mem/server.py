"""lm-mem MCP Server — Claude 本地语义(向量)记忆,Mem0 风格接口。

- 框架: FastMCP (官方 mcp 包), stdio 传输
- 存储/检索: ChromaDB 本地持久化 + 内置 all-MiniLM-L6-v2 embedding
  语义检索开箱即用,无需任何 API key(首次运行自动下载模型,约 80MB)。

作用域(scope):每条记忆可归属到 user_id / agent_id / app_id / run_id,
检索和列举都可按这些维度过滤,对齐 Mem0 的实体模型。

记忆库默认落盘到 ${CLAUDE_PLUGIN_DATA}/chroma(插件更新后依然保留);
未设置该变量时回退到 ~/.claude/lm-mem/chroma。
"""

import json
import os
import time
import uuid
from pathlib import Path

import chromadb
from mcp.server.fastmcp import FastMCP

_data_root = os.environ.get("CLAUDE_PLUGIN_DATA") or str(
    Path.home() / ".claude" / "lm-mem"
)
DB_PATH = os.environ.get("MEMORY_DB_PATH", str(Path(_data_root) / "chroma"))
Path(DB_PATH).mkdir(parents=True, exist_ok=True)

_client = chromadb.PersistentClient(path=DB_PATH)
_collection = _client.get_or_create_collection(
    name="memories",
    metadata={"hnsw:space": "cosine"},
)

mcp = FastMCP("lm-mem")

# 作用域字段:归属实体的维度。
_SCOPE_KEYS = ("user_id", "agent_id", "app_id", "run_id")


def _scope_meta(user_id, agent_id, app_id, run_id):
    """把作用域参数拼成 metadata(空值不写入,ChromaDB 不接受 None)。"""
    meta = {}
    for key, val in zip(_SCOPE_KEYS, (user_id, agent_id, app_id, run_id)):
        if val:
            meta[key] = val
    return meta


def _scope_where(user_id, agent_id, app_id, run_id):
    """把作用域参数拼成 ChromaDB 的 where 过滤条件。"""
    clauses = [
        {key: val}
        for key, val in zip(_SCOPE_KEYS, (user_id, agent_id, app_id, run_id))
        if val
    ]
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _fmt(mem_id, doc, meta):
    meta = meta or {}
    scope = {k: meta[k] for k in _SCOPE_KEYS if k in meta}
    tags = meta.get("tags") or "-"
    scope_str = json.dumps(scope, ensure_ascii=False) if scope else "-"
    return f"id={mem_id}\n  内容: {doc}\n  作用域: {scope_str}\n  标签: {tags}"


@mcp.tool()
def add_memory(
    content: str,
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
    tags: str = "",
) -> str:
    """保存一条记忆(可绑定 user/agent/app/run 作用域)。

    Args:
        content: 要记住的文本或对话内容。
        user_id / agent_id / app_id / run_id: 可选,记忆归属的实体。
        tags: 可选,逗号分隔的标签。
    Returns:
        新记忆的 id。
    """
    mem_id = str(uuid.uuid4())
    meta = {"created_at": time.time(), "tags": tags.strip()}
    meta.update(_scope_meta(user_id, agent_id, app_id, run_id))
    _collection.add(ids=[mem_id], documents=[content], metadatas=[meta])
    return f"已保存记忆 id={mem_id}"


@mcp.tool()
def search_memories(
    query: str,
    limit: int = 5,
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
) -> str:
    """按语义相似度检索记忆,可用作用域过滤。

    Args:
        query: 检索问题/关键词(自然语言)。
        limit: 返回的最大条数,默认 5。
        user_id / agent_id / app_id / run_id: 可选,限定检索范围。
    """
    if _collection.count() == 0:
        return "记忆库为空。"

    where = _scope_where(user_id, agent_id, app_id, run_id)
    res = _collection.query(query_texts=[query], n_results=limit, where=where)
    ids = res["ids"][0]
    if not ids:
        return "没有匹配的记忆。"

    lines = []
    for mem_id, doc, meta, dist in zip(
        ids, res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        lines.append(f"[相似度 {1 - dist:.2f}] " + _fmt(mem_id, doc, meta))
    return "\n\n".join(lines)


@mcp.tool()
def get_memories(
    limit: int = 50,
    offset: int = 0,
    user_id: str = "",
    agent_id: str = "",
    app_id: str = "",
    run_id: str = "",
) -> str:
    """列出记忆,支持作用域过滤与分页。

    Args:
        limit: 每页条数,默认 50。
        offset: 偏移量,用于翻页,默认 0。
        user_id / agent_id / app_id / run_id: 可选,限定范围。
    """
    where = _scope_where(user_id, agent_id, app_id, run_id)
    res = _collection.get(
        where=where, limit=limit, offset=offset, include=["documents", "metadatas"]
    )
    if not res["ids"]:
        return "没有匹配的记忆。"

    lines = [
        _fmt(mem_id, doc, meta)
        for mem_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"])
    ]
    return f"返回 {len(lines)} 条(offset={offset}):\n\n" + "\n\n".join(lines)


@mcp.tool()
def get_memory(mem_id: str) -> str:
    """按 id 获取单条记忆。"""
    res = _collection.get(ids=[mem_id], include=["documents", "metadatas"])
    if not res["ids"]:
        return f"未找到 id={mem_id} 的记忆。"
    return _fmt(res["ids"][0], res["documents"][0], res["metadatas"][0])


@mcp.tool()
def update_memory(mem_id: str, content: str) -> str:
    """按 id 覆盖记忆文本(保留原作用域与标签)。

    Args:
        mem_id: 记忆 id。
        content: 新的文本内容。
    """
    existing = _collection.get(ids=[mem_id], include=["metadatas"])
    if not existing["ids"]:
        return f"未找到 id={mem_id} 的记忆。"
    meta = existing["metadatas"][0] or {}
    meta["updated_at"] = time.time()
    _collection.update(ids=[mem_id], documents=[content], metadatas=[meta])
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
