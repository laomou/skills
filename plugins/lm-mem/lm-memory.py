#!/usr/bin/env python3
"""lm-mem 统一管理脚本。

管理三个进程:
  backend  Chroma 常驻后端(端口 8901) — systemd 用户服务
  web      Web UI(端口 7531) — systemd 用户服务
  mcp      MCP server(stdio,供 Claude Code 调用)

用法:
  python lm-memory.py backend start|stop|restart|status
  python lm-memory.py web     start|stop|restart|status
  python lm-memory.py mcp
  python lm-memory.py start                  # 后端 + Web
  python lm-memory.py stop                   # 后端 + Web
  python lm-memory.py status                 # 后端 + Web

首次安装:
  cd plugins/lm-mem/systemd
  ./install.sh start
"""
from __future__ import annotations

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
CHROMA_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"


def _w(s):
    print(s, file=sys.stderr)


def _sc(args: list[str]) -> subprocess.CompletedProcess:
    """systemctl --user 调用。"""
    return subprocess.run(["systemctl", "--user"] + args,
                          capture_output=True, text=True)


# ── backend ──────────────────────────────────────────


def _backend_running():
    return _sc(["is-active", "lm-mem-backend.service"]).returncode == 0


def _backend_start():
    _sc(["start", "lm-mem-backend.service"])
    for _ in range(60):
        if _backend_running():
            _w("后端已就绪")
            return
        time.sleep(0.5)
    _w("后端启动超时")
    _w(_sc(["status", "lm-mem-backend.service"]).stdout)
    sys.exit(1)


def _backend_stop():
    _sc(["stop", "lm-mem-backend.service"])
    _w("后端已停止")


def _backend_status():
    r = _sc(["status", "lm-mem-backend.service"])
    _w(r.stdout[:300] if r.stdout else ("后端未安装" if r.returncode else "后端未运行"))


# ── web ──────────────────────────────────────────────


def _web_running():
    return _sc(["is-active", "lm-mem-web.service"]).returncode == 0


def _web_start(host=None, port=None):
    host = host or WEB_HOST
    port = port or WEB_PORT
    if _web_running():
        _w(f"Web UI 已在运行:http://{host}:{port}")
        return
    _w(f"启动 Web UI → http://{host}:{port}")
    env = os.environ.copy()
    env["MEMORY_CHROMA_URL"] = CHROMA_URL
    env["LM_MEM_WEB_HOST"] = host
    env["LM_MEM_WEB_PORT"] = str(port)
    proc = subprocess.Popen(
        [str(VENV_PYTHON), str(ROOT / "web.py")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True,
        env=env,
    )
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://{host}:{port}/version", timeout=2)
            _w(f"Web UI 已就绪 (pid={proc.pid})")
            return
        except Exception:
            time.sleep(0.5)
    _w("Web UI 启动超时")
    sys.exit(1)


def _web_stop(host=None, port=None):
    import urllib.request, signal
    host = host or WEB_HOST
    port = port or WEB_PORT
    import subprocess as _sp
    p = _sp.run(["pkill", "-f", "python.*web.py"], capture_output=True)
    if p.returncode == 0:
        _w("Web UI 已停止")
        return
    try:
        urllib.request.urlopen(f"http://{host}:{port}/version", timeout=2)
        _w("Web UI 未通过 pid 管理,请手动停止")
    except Exception:
        _w("Web UI 未运行")


def _web_status(host=None, port=None):
    host = host or WEB_HOST
    port = port or WEB_PORT
    import urllib.request
    try:
        urllib.request.urlopen(f"http://{host}:{port}/version", timeout=2)
        _w(f"Web UI 运行中:http://{host}:{port}")
    except Exception:
        _w("Web UI 未运行")


# ── mcp ──────────────────────────────────────────────


def _mcp_run():
    """在前台启动 MCP server(stdio 模式,供 Claude Code 调用)。"""
    env = os.environ.copy()
    env["MEMORY_CHROMA_URL"] = CHROMA_URL
    os.execve(
        str(ROOT / ".venv" / "bin" / "python"),
        [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "server.py")],
        env,
    )


# ── CLI ──────────────────────────────────────────────


def _dispatch():
    args = sys.argv[1:]
    if not args:
        _w("用法: python lm-memory.py {backend|web|mcp|start|stop|status} [start|stop|restart|status]")
        sys.exit(1)

    cmd = args[0]

    # mcp 子命令
    if cmd == "mcp":
        _mcp_run()
        return

    # 复合子命令
    if cmd in ("start", "stop", "status"):
        sub = args[1] if len(args) > 1 else None
        targets = []
        if sub is None or sub == "all":
            _backend_start if cmd == "start" else (_backend_stop if cmd == "stop" else _backend_status)
            targets = [("backend", _backend_start if cmd == "start" else _backend_stop if cmd == "stop" else _backend_status),
                       ("web", _web_start if cmd == "start" else _web_stop if cmd == "stop" else _web_status)]
        elif sub == "backend":
            targets = [("backend", _backend_start if cmd == "start" else _backend_stop if cmd == "stop" else _backend_status)]
        elif sub == "web":
            targets = [("web", _web_start if cmd == "start" else _web_stop if cmd == "stop" else _web_status)]
        else:
            _w(f"未知目标:{sub}")
            sys.exit(1)
        for name, fn in targets:
            _w(f"--- {name} ---")
            fn()
        return

    # backend/web 子命令 + action
    action = args[1] if len(args) > 1 else "status"
    # 解析 --host --port 参数
    rest = args[2:]
    web_host = None
    web_port = None
    i = 0
    while i < len(rest):
        if rest[i] == "--host" and i + 1 < len(rest):
            web_host = rest[i + 1]
            i += 2
        elif rest[i] == "--port" and i + 1 < len(rest):
            web_port = int(rest[i + 1])
            i += 2
        else:
            i += 1
    if cmd == "backend":
        fn = {"start": _backend_start, "stop": _backend_stop,
              "restart": lambda: (_backend_stop(), time.sleep(1), _backend_start()),
              "status": _backend_status}.get(action)
    elif cmd == "web":
        if action == "start":
            fn = lambda: _web_start(web_host, web_port)
        elif action == "stop":
            fn = lambda: _web_stop(web_host, web_port)
        elif action == "restart":
            fn = lambda: (_web_stop(web_host, web_port), time.sleep(1), _web_start(web_host, web_port))
        elif action == "status":
            fn = lambda: _web_status(web_host, web_port)
        else:
            fn = None
    else:
        _w(f"未知命令:{cmd}")
        _w("可用: backend|web|mcp|start|stop|status")
        sys.exit(1)
    if not fn:
        _w(f"未知操作:{action}(可用:start|stop|restart|status)")
        sys.exit(1)
    fn()


if __name__ == "__main__":
    _dispatch()