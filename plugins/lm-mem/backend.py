"""lm-mem 存储后端客户端连接。

MCP 进程只当纯客户端,连接外部常驻后端(由 manage.py 托管)。
后端生命周期完全独立于 MCP。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import chromadb

_data_root = os.environ.get("LM_MEM_DATA_DIR") or str(Path.home() / ".lm-mem")
DB_PATH = os.environ.get("LM_MEM_DB_PATH", str(Path(_data_root) / "chroma"))
Path(DB_PATH).mkdir(parents=True, exist_ok=True)


def _connect(host, port):
    """尝试连接后端;连不上返回 None(不抛异常)。"""
    try:
        client = chromadb.HttpClient(host=host, port=port)
        client.heartbeat()
        return client
    except Exception:
        return None


def _in_pytest():
    return "pytest" in sys.modules


def _embedded_client():
    return chromadb.PersistentClient(path=DB_PATH)


def _connect_or_raise(url):
    u = urlparse(url if "://" in url else f"http://{url}")
    host = u.hostname or "127.0.0.1"
    port = u.port or 8000
    client = _connect(host, port)
    if client is None:
        raise RuntimeError(
            f"后端 {host}:{port} 连接失败。"
            f"请先用 manage.py backend start 启动后端。"
        )
    return client


def _init_client():
    """初始化 client(纯客户端模式)。

    通过 LM_MEM_BACKEND_URL 连接常驻后端。
    MCP 自身不再 spawn 任何后端进程,连不上直接报错。
    pytest 下使用嵌入式模式(测试隔离)。
    """
    if url := os.environ.get("LM_MEM_BACKEND_URL", "").strip():
        return _connect_or_raise(url)
    if _in_pytest():
        return _embedded_client()
    raise RuntimeError(
        "未设置 LM_MEM_BACKEND_URL,无法连接后端。"
        "请在 .mcp.json 的 env 中添加 LM_MEM_BACKEND_URL=http://127.0.0.1:8901"
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
