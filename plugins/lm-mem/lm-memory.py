#!/usr/bin/env python3
"""lm-mem 统一管理脚本。

管理三个进程:
  backend  Chroma 常驻后端(端口 8901)
  web      Web UI(端口 7531)
  mcp      MCP server(stdio,供 Claude Code 调用)

用法:
  python lm-memory.py backend start|stop|restart|status
  python lm-memory.py web     start|stop|restart|status
  python lm-memory.py mcp
  python lm-memory.py start                  # 后端 + Web
  python lm-memory.py stop                   # 后端 + Web
  python lm-memory.py status                 # 后端 + Web
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
VENV_CHROMA = ROOT / ".venv" / "bin" / "chroma"
HOME = Path.home()
DATA_DIR = Path(os.environ.get("CLAUDE_PLUGIN_DATA", str(HOME / ".claude" / "lm-mem")))
DB_PATH = Path(os.environ.get("MEMORY_DB_PATH", str(DATA_DIR / "chroma")))

PID_DIR = DATA_DIR / "pids"
PID_DIR.mkdir(parents=True, exist_ok=True)
PID_FILES = {
    "backend": PID_DIR / "backend.pid",
    "web": PID_DIR / "web.pid",
}
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILES = {
    "backend": LOG_DIR / "backend.log",
    "web": LOG_DIR / "web.log",
}

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8901
WEB_HOST = os.environ.get("LM_MEM_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("LM_MEM_WEB_PORT", "7531"))
CHROMA_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"


def _w(s):
    print(s, file=sys.stderr)


# ── backend ──────────────────────────────────────────


def _backend_running():
    import urllib.request

    try:
        urllib.request.urlopen(f"{CHROMA_URL}/api/v2/heartbeat", timeout=2)
        return True
    except Exception:
        return False


def _backend_pid():
    try:
        return int(PID_FILES["backend"].read_text().strip())
    except Exception:
        return None


def _backend_start():
    if _backend_running():
        _w(f"后端已在运行:{CHROMA_URL}")
        return
    DB_PATH.mkdir(parents=True, exist_ok=True)
    _w(f"启动后端 → {CHROMA_URL}")
    cmd = [str(VENV_CHROMA), "run", "--path", str(DB_PATH),
           "--host", BACKEND_HOST, "--port", str(BACKEND_PORT)]
    log = open(LOG_FILES["backend"], "ab")
    kwargs = dict(stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    proc = subprocess.Popen(cmd, **kwargs)
    PID_FILES["backend"].write_text(str(proc.pid))
    for _ in range(60):
        if _backend_running():
            _w(f"后端已就绪 (pid={proc.pid})")
            return
        time.sleep(0.5)
    _w("后端启动超时,查看日志:" + str(LOG_FILES["backend"]))
    sys.exit(1)


def _backend_stop():
    pid = _backend_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            _w(f"后端已停止 (pid={pid})")
        except ProcessLookupError:
            _w("后端进程不存在")
        PID_FILES["backend"].unlink(missing_ok=True)
    else:
        import subprocess as _sp
        p = _sp.run(["pkill", "-f", f"run.*--path.*{DB_PATH}.*--host.*{BACKEND_HOST}"],
                     capture_output=True)
        _w("后端已停止" if p.returncode == 0 else "后端未运行")


def _backend_status():
    running = _backend_running()
    pid = _backend_pid()
    if running:
        _w(f"运行中:{CHROMA_URL}" + (f" (pid={pid})" if pid else ""))
    else:
        _w("后端未运行")


# ── web ──────────────────────────────────────────────


def _web_running():
    import urllib.request

    try:
        urllib.request.urlopen(f"http://{WEB_HOST}:{WEB_PORT}/version", timeout=2)
        return True
    except Exception:
        return False


def _web_pid():
    try:
        return int(PID_FILES["web"].read_text().strip())
    except Exception:
        return None


def _web_start():
    if _web_running():
        _w(f"Web UI 已在运行:http://{WEB_HOST}:{WEB_PORT}")
        return
    _w(f"启动 Web UI → http://{WEB_HOST}:{WEB_PORT}")
    env = os.environ.copy()
    env["MEMORY_CHROMA_URL"] = CHROMA_URL
    env["LM_MEM_WEB_HOST"] = WEB_HOST
    env["LM_MEM_WEB_PORT"] = str(WEB_PORT)
    cmd = [str(VENV_PYTHON), str(ROOT / "web.py")]
    log = open(LOG_FILES["web"], "ab")
    kwargs = dict(stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                  start_new_session=True, env=env)
    proc = subprocess.Popen(cmd, **kwargs)
    PID_FILES["web"].write_text(str(proc.pid))
    for _ in range(30):
        if _web_running():
            _w(f"Web UI 已就绪 (pid={proc.pid})")
            return
        time.sleep(0.5)
    _w("Web UI 启动超时,查看日志:" + str(LOG_FILES["web"]))
    sys.exit(1)


def _web_stop():
    pid = _web_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            _w(f"Web UI 已停止 (pid={pid})")
        except ProcessLookupError:
            _w("Web UI 进程不存在")
        PID_FILES["web"].unlink(missing_ok=True)
    else:
        import subprocess as _sp
        p = _sp.run(["pkill", "-f", "python.*web.py"], capture_output=True)
        _w("Web UI 已停止" if p.returncode == 0 else "Web UI 未运行")


def _web_status():
    running = _web_running()
    pid = _web_pid()
    if running:
        _w(f"Web UI 运行中:http://{WEB_HOST}:{WEB_PORT}" +
           (f" (pid={pid})" if pid else ""))
    else:
        _w("Web UI 未运行")


# ── mcp ──────────────────────────────────────────────


def _mcp_run():
    """在前台启动 MCP server(stdio 模式,供 Claude Code 调用)。"""
    env = os.environ.copy()
    env["MEMORY_CHROMA_URL"] = CHROMA_URL
    os.execve(str(VENV_PYTHON), [str(VENV_PYTHON), str(ROOT / "server.py")], env)


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
    if cmd == "backend":
        fn = {"start": _backend_start, "stop": _backend_stop,
              "restart": lambda: (_backend_stop(), time.sleep(1), _backend_start()),
              "status": _backend_status}.get(action)
    elif cmd == "web":
        fn = {"start": _web_start, "stop": _web_stop,
              "restart": lambda: (_web_stop(), time.sleep(1), _web_start()),
              "status": _web_status}.get(action)
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