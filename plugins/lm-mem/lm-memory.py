#!/usr/bin/env python3
"""lm-mem 统一管理脚本。

用法:
  python lm-memory.py backend start|stop|restart|status [--host HOST] [--port PORT]
  python lm-memory.py web     start|stop|restart|status [--host HOST] [--port PORT]
  python lm-memory.py mcp
  python lm-memory.py start|stop|status               [--host HOST] [--port PORT]

首次安装:
  cd plugins/lm-mem/systemd
  ./install.sh start
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8901
WEB_HOST = os.environ.get("LM_MEM_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("LM_MEM_WEB_PORT", "7531"))


def _w(s):
    print(s, file=sys.stderr)


def _sc(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user"] + args, capture_output=True, text=True)


# ── backend ──────────────────────────────────────────


def _backend_start(host=BACKEND_HOST, port=BACKEND_PORT):
    _sc(["start", "lm-mem-backend.service"])
    for _ in range(60):
        if _sc(["is-active", "lm-mem-backend.service"]).returncode == 0:
            _w(f"后端已就绪 → http://{host}:{port}")
            return
        time.sleep(0.5)
    _w("后端启动超时")
    _w(_sc(["status", "lm-mem-backend.service"]).stdout)
    sys.exit(1)


def _backend_stop(_host=None, _port=None):
    _sc(["stop", "lm-mem-backend.service"])
    _w("后端已停止")


def _backend_status(host=BACKEND_HOST, port=BACKEND_PORT):
    import urllib.request

    try:
        urllib.request.urlopen(f"http://{host}:{port}/api/v2/heartbeat", timeout=2)
        _w(f"后端运行中:http://{host}:{port}")
    except Exception:
        _w("后端未运行")


# ── web ──────────────────────────────────────────────


def _web_start(host=WEB_HOST, port=WEB_PORT):
    import urllib.request

    try:
        urllib.request.urlopen(f"http://{host}:{port}/version", timeout=2)
        _w(f"Web UI 已在运行:http://{host}:{port}")
        return
    except Exception:
        pass
    _w(f"启动 Web UI → http://{host}:{port}")
    env = os.environ.copy()
    env["MEMORY_CHROMA_URL"] = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
    env["LM_MEM_WEB_HOST"] = host
    env["LM_MEM_WEB_PORT"] = str(port)
    proc = subprocess.Popen(
        [str(VENV_PYTHON), str(ROOT / "web.py")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True, env=env,
    )
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://{host}:{port}/version", timeout=2)
            _w(f"Web UI 已就绪 (pid={proc.pid})")
            return
        except Exception:
            time.sleep(0.5)
    _w("Web UI 启动超时")
    sys.exit(1)


def _web_stop(_host=None, _port=None):
    p = subprocess.run(["pkill", "-f", "python.*web.py"], capture_output=True)
    _w("Web UI 已停止" if p.returncode == 0 else "Web UI 未运行")


def _web_status(host=WEB_HOST, port=WEB_PORT):
    import urllib.request

    try:
        urllib.request.urlopen(f"http://{host}:{port}/version", timeout=2)
        _w(f"Web UI 运行中:http://{host}:{port}")
    except Exception:
        _w("Web UI 未运行")


# ── mcp ──────────────────────────────────────────────


def _mcp_run():
    env = os.environ.copy()
    env["MEMORY_CHROMA_URL"] = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
    os.execve(str(VENV_PYTHON), [str(VENV_PYTHON), str(ROOT / "mcp_tools.py")], env)


# ── CLI ──────────────────────────────────────────────


def _build_parser():
    p = argparse.ArgumentParser(description="lm-mem 统一管理脚本")

    # 共享的 host/port 参数(用于子命令)
    conn = argparse.ArgumentParser(add_help=False)
    conn.add_argument("--host", default=None, help="绑定地址或连接地址")
    conn.add_argument("--port", type=int, default=None, help="绑定端口或连接端口")

    sub = p.add_subparsers(dest="entity", required=True)

    # mcp
    sub.add_parser("mcp", parents=[conn], help="前台运行 MCP server")

    # start/stop/status
    for name in ("start", "stop", "status"):
        sp = sub.add_parser(name, parents=[conn], help=f"{name} 后端+Web")
        sp.add_argument("target", nargs="?", default="all",
                        choices=["all", "backend", "web"],
                        help="目标(默认 all)")

    # backend/web
    for entity in ("backend", "web"):
        ep = sub.add_parser(entity, parents=[conn], help=f"{entity} 管理")
        ep.add_argument("action", nargs="?", default="status",
                        choices=["start", "stop", "restart", "status"])
    return p


def _dispatch():
    p = _build_parser()
    args = p.parse_args()

    entity = args.entity

    if entity == "mcp":
        _mcp_run()
        return

    host = args.host
    port = args.port

    if entity in ("start", "stop", "status"):
        target = getattr(args, "target", "all")
        tasks = []
        if target in ("all", "backend"):
            bh = host or BACKEND_HOST
            bp = port or BACKEND_PORT
            if entity == "start":
                tasks.append(("backend", lambda: _backend_start(bh, bp)))
            elif entity == "stop":
                tasks.append(("backend", _backend_stop))
            else:
                tasks.append(("backend", lambda: _backend_status(bh, bp)))
        if target in ("all", "web"):
            wh = host or WEB_HOST
            wp = port or WEB_PORT
            if entity == "start":
                tasks.append(("web", lambda: _web_start(wh, wp)))
            elif entity == "stop":
                tasks.append(("web", _web_stop))
            else:
                tasks.append(("web", lambda: _web_status(wh, wp)))
        for name, fn in tasks:
            _w(f"--- {name} ---")
            fn()
        return

    if entity in ("backend", "web"):
        action = args.action
        kwargs = {}
        if host:
            kwargs["host"] = host
        if port:
            kwargs["port"] = port

        if action == "start":
            fn = _backend_start if entity == "backend" else _web_start
            fn(**kwargs)
        elif action == "stop":
            fn = _backend_stop if entity == "backend" else _web_stop
            fn(**kwargs)
        elif action == "restart":
            stop = _backend_stop if entity == "backend" else _web_stop
            start = _backend_start if entity == "backend" else _web_start
            stop(**kwargs)
            time.sleep(1)
            start(**kwargs)
        elif action == "status":
            fn = _backend_status if entity == "backend" else _web_status
            fn(**kwargs)
        return


if __name__ == "__main__":
    _dispatch()