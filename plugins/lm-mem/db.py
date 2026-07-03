"""lm-mem Chroma 客户端连接。

依赖 chromadb 与标准库。零依赖 helpers.py/mcp_tools.py/web.py。

MCP 进程只当纯客户端,连接外部常驻 Chroma 后端(由 chroma-backend.sh 托管)。
后端生命周期完全独立于 MCP。
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import chromadb

_data_root = os.environ.get("CLAUDE_PLUGIN_DATA") or str(
    Path.home() / ".claude" / "lm-mem"
)
DB_PATH = os.environ.get("MEMORY_DB_PATH", str(Path(_data_root) / "chroma"))
Path(DB_PATH).mkdir(parents=True, exist_ok=True)


def _connect(host, port):
    """尝试连接一个 Chroma 后端;连不上返回 None(不抛异常)。"""
    try:
        client = chromadb.HttpClient(host=host, port=port)
        client.heartbeat()
        return client
    except Exception:
        return None


def _init_client():
    """初始化 chromadb client(纯客户端模式)。

    通过 MEMORY_CHROMA_URL 连接常驻 Chroma 后端。
    MCP 自身不再 spawn 任何后端进程,连不上直接报错。
    pytest 下使用嵌入式 PersistentClient(测试隔离)。
    """
    url = os.environ.get("MEMORY_CHROMA_URL", "").strip()
    if url:
        u = urlparse(url if "://" in url else f"http://{url}")
        host = u.hostname or "127.0.0.1"
        port = u.port or 8000
        client = _connect(host, port)
        if client is None:
            raise RuntimeError(
                f"Chroma 后端 {host}:{port} 连接失败。"
                f"请先用 chroma-backend.sh start 启动后端。"
            )
        return client

    # pytest 走嵌入式(测试隔离)
    if "pytest" in __import__("sys").modules:
        return chromadb.PersistentClient(path=DB_PATH)

    raise RuntimeError(
        "未设置 MEMORY_CHROMA_URL,无法连接 Chroma 后端。"
        "请在 .mcp.json 的 env 中添加 MEMORY_CHROMA_URL=http://127.0.0.1:8901"
    )


_client = _init_client()
_collection = _client.get_or_create_collection(
    name="memories",
    metadata={
        "hnsw:space": "cosine",
        "hnsw:M": 4,
        "hnsw:construction_ef": 30,
        "hnsw:search_ef": 2,
        "hnsw:num_threads": 20,
    },
)
