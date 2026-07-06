#!/usr/bin/env python3
"""lm-mem 统一管理脚本。

用法:
  python manage.py backend start|stop|restart|status [--host HOST] [--port PORT]
  python manage.py web     start|stop|restart|status [--host HOST] [--port PORT]
  python manage.py mcp
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
VENV_CHROMA = ROOT / ".venv" / "bin" / "chroma"
_DATA_ROOT = os.environ.get("LM_MEM_DATA_DIR") or str(Path.home() / ".lm-mem")
PID_DIR = Path(_DATA_ROOT) / "pids"
PID_DIR.mkdir(parents=True, exist_ok=True)
BACKEND_PID_FILE = PID_DIR / "backend.pid"
WEB_PID_FILE = PID_DIR / "web.pid"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8901
WEB_HOST = os.environ.get("LM_MEM_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("LM_MEM_WEB_PORT", "7531"))


def _w(s):
    print(s, file=sys.stderr)


# ── backend ──────────────────────────────────────────


def _backend_url(host, port):
    return f"http://{host}:{port}/api/v2/heartbeat"


def _backend_running(host, port):
    try:
        urllib.request.urlopen(_backend_url(host, port), timeout=2)
        return True
    except Exception:
        return False


def _backend_defaults(host, port):
    return host or BACKEND_HOST, port or BACKEND_PORT


def _backend_start(host=None, port=None):
    host, port = _backend_defaults(host, port)
    if _backend_running(host, port):
        _w(f"后端已在运行:http://{host}:{port}")
        return
    _w(f"启动后端 → http://{host}:{port}")
    DB_PATH = _get_db_path()
    log = open(str(PID_DIR.parent / "logs" / "backend.log"), "ab")
    proc = subprocess.Popen(
        [str(VENV_CHROMA), "run", "--path", DB_PATH, "--host", host, "--port", str(port)],
        stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
    )
    BACKEND_PID_FILE.write_text(str(proc.pid))
    for _ in range(60):
        if _backend_running(host, port):
            _w(f"后端已就绪 (pid={proc.pid})")
            return
        time.sleep(0.5)
    _w("后端启动超时")
    sys.exit(1)


def _backend_stop(host=None, port=None):
    if BACKEND_PID_FILE.exists():
        pid = int(BACKEND_PID_FILE.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            _w(f"后端已停止 (pid={pid})")
            BACKEND_PID_FILE.unlink(missing_ok=True)
            return
        except ProcessLookupError:
            BACKEND_PID_FILE.unlink(missing_ok=True)
    host, port = _backend_defaults(host, port)
    p = subprocess.run(["pkill", "-f", f"chroma.*run.*--port {port}"], capture_output=True)
    _w("后端已停止" if p.returncode == 0 else "后端未运行")


def _backend_status(host=None, port=None):
    host, port = _backend_defaults(host, port)
    if _backend_running(host, port):
        _w(f"后端运行中:http://{host}:{port}")
    else:
        _w("后端未运行")


def _get_db_path():
    return os.environ.get("LM_MEM_DB_PATH", str(Path(_DATA_ROOT) / "chroma"))


# ── web ──────────────────────────────────────────────


def _web_running(host, port):
    try:
        urllib.request.urlopen(f"http://{host}:{port}/version", timeout=2)
        return True
    except Exception:
        return False


def _web_defaults(host, port):
    return host or WEB_HOST, port or WEB_PORT


def _web_start(host=None, port=None):
    host, port = _web_defaults(host, port)
    if _web_running(host, port):
        _w(f"Web UI 已在运行:http://{host}:{port}")
        return
    _w(f"启动 Web UI → http://{host}:{port}")
    env = os.environ.copy()
    env["LM_MEM_BACKEND_URL"] = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
    env["LM_MEM_WEB_HOST"] = host
    env["LM_MEM_WEB_PORT"] = str(port)
    proc = subprocess.Popen(
        [str(VENV_PYTHON), str(ROOT / "web.py")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True, env=env,
    )
    WEB_PID_FILE.write_text(str(proc.pid))
    for _ in range(30):
        if _web_running(host, port):
            _w(f"Web UI 已就绪 (pid={proc.pid})")
            return
        time.sleep(0.5)
    _w("Web UI 启动超时")
    sys.exit(1)


def _web_stop(_host=None, _port=None):
    if WEB_PID_FILE.exists():
        pid = int(WEB_PID_FILE.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            _w(f"Web UI 已停止 (pid={pid})")
            WEB_PID_FILE.unlink(missing_ok=True)
            return
        except ProcessLookupError:
            WEB_PID_FILE.unlink(missing_ok=True)
    p = subprocess.run(["pkill", "-f", "python.*web.py"], capture_output=True)
    _w("Web UI 已停止" if p.returncode == 0 else "Web UI 未运行")


def _web_status(host=None, port=None):
    host, port = _web_defaults(host, port)
    if _web_running(host, port):
        _w(f"Web UI 运行中:http://{host}:{port}")
    else:
        _w("Web UI 未运行")


# ── mcp ──────────────────────────────────────────────


def _mcp_run():
    """在当前进程内加载并运行 MCP server(stdio 模式)。"""
    os.environ["LM_MEM_BACKEND_URL"] = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
    from mcp_tools import mcp
    mcp.run()


# ── CLI ──────────────────────────────────────────────


def _build_parser():
    p = argparse.ArgumentParser(description="lm-mem 统一管理脚本")
    conn = argparse.ArgumentParser(add_help=False)
    conn.add_argument("--host", default=None, help="绑定地址或连接地址")
    conn.add_argument("--port", type=int, default=None, help="绑定端口或连接端口")

    sub = p.add_subparsers(dest="entity", required=True)
    sub.add_parser("mcp", help="前台运行 MCP server")

    for entity in ("backend", "web"):
        ep = sub.add_parser(entity, parents=[conn], help=f"{entity} 管理")
        ep.add_argument("action", nargs="?", default="status",
                        choices=["start", "stop", "restart", "status"])
    return p


_HANDLERS = {
    "backend": {"start": _backend_start, "stop": _backend_stop, "status": _backend_status},
    "web": {"start": _web_start, "stop": _web_stop, "status": _web_status},
}


def _run(entity, action, host, port):
    if entity == "mcp":
        _mcp_run()
        return
    if entity not in _HANDLERS:
        _w(f"未知实体:{entity}")
        sys.exit(1)
    if action == "restart":
        _HANDLERS[entity]["stop"](host, port)
        time.sleep(1)
        _HANDLERS[entity]["start"](host, port)
    else:
        _HANDLERS[entity][action](host, port)


def main():
    p = _build_parser()
    args = p.parse_args()
    _run(args.entity, getattr(args, "action", ""), args.host, args.port)


if __name__ == "__main__":
    main()