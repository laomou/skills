"""lm-mem MCP Server — 垫片模块。

为保持向后兼容(测试 import server, .mcp.json 调 server.py),
将 helpers / db / mcp_tools 中的全部符号 re-export 到本模块命名空间。
"""
from __future__ import annotations

from db import _client, _collection, _connect, _ensure_backend, _init_client, _spawn_chroma
from helpers import (
    _clauses,
    _coerce_scalar,
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
    _RESERVED_KEYS,
    _SCOPE_KEYS,
    _scope_meta,
    _scope_where,
    _user_metadata,
)
from mcp_tools import (
    mcp,
    add_memory,
    delete_all_memories,
    delete_entities,
    delete_memory,
    export_memories,
    get_memories,
    get_memory,
    list_entities,
    memory_stats,
    purge_expired,
    search_memories,
    update_memory,
)

main = mcp.run

if __name__ == "__main__":
    main()