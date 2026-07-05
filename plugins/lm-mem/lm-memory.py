#!/usr/bin/env python3
"""lm-mem 统一管理脚本。

用法:
  python lm-memory.py backend start|stop|restart|status [--host HOST] [--port PORT]
  python lm-memory.py web     start|stop|restart|status [--host HOST] [--port PORT]
  python lm-memory.py mcp
  python lm-memory.py start|stop|status               [--host HOST] [--port PORT]
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
PID_DIR = Path(os.environ.get("CLAUDE_PLUGIN_DATA",
                str(Path.home() / ".claude" / "lm-mem"))) / "pids"
PID_DIR.mkdir(parents=True, exist_ok=True)
WEB_PID_FILE = PID_DIR / "web.pid"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8901
WEB_HOST = os.environ.get("LM_MEM_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("LM_MEM_WEB_PORT", "7531"))


def _w(s):
    print(s, file=sys.stderr)


def _sc(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user"] + args, capture_output=True, text=True)


def _systemd_installed(name: str) -> bool:
    r = _sc(["list-unit-files", f"{name}.service"])
    return r.returncode == 0 and name in r.stdout


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

    # 用户自定义 host/port → 直接 nohup 起(绕过 systemd)
    if host != BACKEND_HOST or port != BACKEND_PORT:
        _w(f"启动后端(nohup) → http://{host}:{port}")
        DB_PATH = _get_db_path()
        log = open(str(PID_DIR.parent / "logs" / "backend.log"), "ab")
        proc = subprocess.Popen(
            [str(VENV_CHROMA), "run", "--path", DB_PATH, "--host", host, "--port", str(port)],
            stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
        )
        for _ in range(60):
            if _backend_running(host, port):
                _w(f"后端已就绪 (pid={proc.pid})")
                return
            time.sleep(0.5)
        _w("后端启动超时")
        sys.exit(1)

    # 默认 → systemd
    if not _systemd_installed("lm-mem-backend"):
        _w("后端 systemd 服务未安装,请先: cd systemd && ./install.sh start")
        _w("或指定 --host --port 临时启动")
        sys.exit(1)
    _sc(["start", "lm-mem-backend.service"])
    for _ in range(60):
        if _sc(["is-active", "lm-mem-backend.service"]).returncode == 0:
            _w(f"后端已就绪 → http://{host}:{port}")
            return
        time.sleep(0.5)
    _w("后端启动超时")
    _w(_sc(["status", "lm-mem-backend.service"]).stdout)
    sys.exit(1)


def _backend_stop(host=None, port=None):
    if _systemd_installed("lm-mem-backend"):
        _sc(["stop", "lm-mem-backend.service"])
        _w("后端已停止")
        return
    host, port = _backend_defaults(host, port)
    if not _backend_running(host, port):
        _w("后端未运行")
        return
    p = subprocess.run(["pkill", "-f", f"chroma.*run.*--port {port}"], capture_output=True)
    if p.returncode == 0:
        _w("后端已停止(按端口匹配)")
    else:
        _w("后端未运行")


def _backend_status(host=None, port=None):
    host, port = _backend_defaults(host, port)
    if _backend_running(host, port):
        _w(f"后端运行中:http://{host}:{port}")
    else:
        _w("后端未运行")


def _get_db_path():
    return os.environ.get("MEMORY_DB_PATH",
                          str(Path.home() / ".claude" / "lm-mem" / "chroma"))


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
    env["MEMORY_CHROMA_URL"] = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
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
    env = os.environ.copy()
    env["MEMORY_CHROMA_URL"] = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
    os.execve(str(VENV_PYTHON), [str(VENV_PYTHON), str(ROOT / "mcp_tools.py")], env)


# ── CLI ──────────────────────────────────────────────


def _build_parser():
    p = argparse.ArgumentParser(description="lm-mem 统一管理脚本")
    conn = argparse.ArgumentParser(add_help=False)
    conn.add_argument("--host", default=None, help="绑定地址或连接地址")
    conn.add_argument("--port", type=int, default=None, help="绑定端口或连接端口")

    sub = p.add_subparsers(dest="entity", required=True)
    sub.add_parser("mcp", help="前台运行 MCP server")

    for name in ("start", "stop", "status"):
        sp = sub.add_parser(name, parents=[conn], help=f"{name} 后端+Web")
        sp.add_argument("target", nargs="?", default="all",
                        choices=["all", "backend", "web"])

    for entity in ("backend", "web"):
        ep = sub.add_parser(entity, parents=[conn], help=f"{entity} 管理")
        ep.add_argument("action", nargs="?", default="status",
                        choices=["start", "stop", "restart", "status"])
    return p


def _run(entity, action, host, port, target):
    if entity == "mcp":
        _mcp_run()
        return

    def _do_entity(e, fn):
        _w(f"--- {e} ---")
        fn()

    if entity in ("start", "stop", "status"):
        if target in ("all", "backend"):
            args = (host, port) if entity != "stop" else ()
            fn = {"start": lambda: _backend_start(host, port),
                  "stop": _backend_stop,
                  "status": lambda: _backend_status(host, port)}[entity]
            _do_entity("backend", fn)
        if target in ("all", "web"):
            fn = {"start": lambda: _web_start(host, port),
                  "stop": _web_stop,
                  "status": lambda: _web_status(host, port)}[entity]
            _do_entity("web", fn)
        return

    if entity in ("backend", "web"):
        if action == "start":
            ({"backend": _backend_start, "web": _web_start}[entity])(host, port)
        elif action == "stop":
            ({"backend": _backend_stop, "web": _web_stop}[entity])(host, port)
        elif action == "status":
            ({"backend": _backend_status, "web": _web_status}[entity])(host, port)
        elif action == "restart":
            stop = {"backend": _backend_stop, "web": _web_stop}[entity]
            start = {"backend": _backend_start, "web": _web_start}[entity]
            stop(host, port)
            time.sleep(1)
            start(host, port)


def _dispatch():
    p = _build_parser()
    args = p.parse_args()
    _run(args.entity, getattr(args, "action", ""), args.host, args.port,
         getattr(args, "target", "all"))


if __name__ == "__main__":
    _dispatch()