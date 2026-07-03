"""lm-mem Chroma 后端连接与生命周期管理。

依赖 chromadb 与标准库。零依赖 helpers.py/mcp_tools.py/web.py。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import chromadb


def _optimize_sqlite(db_path):
    """对 chroma.sqlite3 设置高性能 PRAGMA。

    在已有 chroma 连接之外独立打开一次 SQLite 设置 WAL 等 PRAGMA,
    这些设置持久化在数据库文件中,后续连接(含 chroma 服务端)继承。
    """
    try:
        import sqlite3

        path = str(Path(db_path) / "chroma.sqlite3")
        if not Path(path).exists():
            return
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=268435456")
        conn.commit()
        conn.close()
    except Exception:
        pass  # PRAGMA 优化非致命,失败不影响功能

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


def _chroma_run_cmd(db_path, host, port):
    """定位 chroma 启动命令。

    依次尝试:PATH 里的 chroma / 解释器同级目录的 chroma 脚本(venv 常见) /
    回退用 `python -c` 直接调 chromadb 的 CLI app 入口(不依赖 PATH)。
    """
    log_path = str(Path(_data_root) / "chroma-server.log")
    Path(_data_root).mkdir(parents=True, exist_ok=True)
    run_args = ["run", "--path", db_path, "--host", host, "--port", str(port)]

    exe = shutil.which("chroma")
    if not exe:
        cand = Path(sys.executable).with_name("chroma")
        if cand.exists():
            exe = str(cand)
    if exe:
        return [exe] + run_args, log_path

    code = (
        "import sys; from chromadb.cli.cli import app; "
        "sys.argv=['chroma']+sys.argv[1:]; app()"
    )
    return [sys.executable, "-c", code] + run_args, log_path


def _spawn_chroma(db_path, host, port):
    """后台拉起 Chroma 后端并与父进程脱离(MCP 退出不带走后端)。

    多个实例可能同时走到这里,只有一个能抢到端口,其余会立即退出;
    调用方随后统一进入轮询,最终都连上抢占成功的那个后端。
    """
    cmd, log_path = _chroma_run_cmd(db_path, host, port)
    log = open(log_path, "ab")
    kwargs = {"stdout": log, "stderr": log, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kwargs)
    except Exception:
        pass


def _ensure_backend(host, port, db_path, explicit_url=False, wait_seconds=30.0):
    """确保有一个可用的 Chroma 后端并返回其 HttpClient。

    流程:先试连已有后端;没有则 spawn 一个;轮询等待就绪;始终起不来则
    回退嵌入式 PersistentClient,保证 lm-mem 不因后端问题而不可用。
    explicit_url=True(用户显式给了 MEMORY_CHROMA_URL)时不 spawn、连不上即报错。
    """
    client = _connect(host, port)
    if client is not None:
        _optimize_sqlite(db_path)
        return client
    if explicit_url:
        raise RuntimeError(
            f"MEMORY_CHROMA_URL 指向的 Chroma 后端 {host}:{port} 连接失败,"
            f"且已显式指定 URL 故不自动启动。请确认该后端在运行。"
        )
    _spawn_chroma(db_path, host, port)
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        client = _connect(host, port)
        if client is not None:
            _optimize_sqlite(db_path)
            return client
        time.sleep(0.5)
    print(
        f"[lm-mem] 警告:Chroma 后端 {host}:{port} 未能就绪,回退到嵌入式模式。",
        file=sys.stderr,
    )
    return chromadb.PersistentClient(path=db_path)


def _init_client():
    """初始化 chromadb client。

    默认走共享后端(HttpClient 连同一个常驻 Chroma,由后端独占 DB 与索引,
    天然支持多会话并发)。第一个实例懒启动后端并靠端口抢占保证全局单例。
    设 MEMORY_CHROMA_URL 则连外部已存在的后端(只连不启)。
    后端始终起不来时,_ensure_backend 内部自动回退嵌入式,保证可用。
    """
    url = os.environ.get("MEMORY_CHROMA_URL", "").strip()
    if url:
        u = urlparse(url if "://" in url else f"http://{url}")
        host = u.hostname or "127.0.0.1"
        port = u.port or 8000
        return _ensure_backend(host, port, DB_PATH, explicit_url=True)
    if "pytest" in sys.modules:
        return chromadb.PersistentClient(path=DB_PATH)
    host = os.environ.get("MEMORY_CHROMA_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("MEMORY_CHROMA_PORT", "8901"))
    return _ensure_backend(host, port, DB_PATH)


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
