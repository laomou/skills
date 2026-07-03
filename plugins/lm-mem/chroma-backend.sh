#!/usr/bin/env bash
# lm-mem Chroma 后端常驻管理脚本(nohup 方式)。
#
# 把 Chroma 作为独立常驻进程运行,MCP 端设 MEMORY_CHROMA_URL 只连不启。
# 后端生命周期由本脚本控制,不随 MCP / Claude Code 退出而消失。
#
#   ./chroma-backend.sh start     启动后端(已在跑则跳过)
#   ./chroma-backend.sh stop      停止后端
#   ./chroma-backend.sh restart   重启
#   ./chroma-backend.sh status    查看状态

set -euo pipefail

HOST="127.0.0.1"
PORT="8901"
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="${MEMORY_DB_PATH:-$HOME/.claude/lm-mem/chroma}"
LOG_PATH="$HOME/.claude/lm-mem/chroma-server.log"
PID_PATH="$HOME/.claude/lm-mem/chroma-server.pid"
CHROMA="$PLUGIN_ROOT/.venv/bin/chroma"

mkdir -p "$DB_PATH" "$(dirname "$LOG_PATH")"

_running() {
  # 端口能连上即视为在跑
  curl -sf "http://$HOST:$PORT/api/v2/heartbeat" >/dev/null 2>&1
}

start() {
  if _running; then
    echo "后端已在运行:http://$HOST:$PORT"
    return 0
  fi
  echo "启动 Chroma 后端 → http://$HOST:$PORT (db=$DB_PATH)"
  nohup "$CHROMA" run --path "$DB_PATH" --host "$HOST" --port "$PORT" \
    >>"$LOG_PATH" 2>&1 &
  echo $! >"$PID_PATH"
  # 轮询等待就绪
  for _ in $(seq 1 60); do
    if _running; then
      echo "已就绪 (pid=$(cat "$PID_PATH"))"
      return 0
    fi
    sleep 0.5
  done
  echo "启动超时,查看日志:$LOG_PATH" >&2
  return 1
}

stop() {
  if [ -f "$PID_PATH" ]; then
    pid="$(cat "$PID_PATH")"
    if kill "$pid" 2>/dev/null; then
      echo "已停止 (pid=$pid)"
    else
      echo "进程 $pid 不存在,清理 pid 文件"
    fi
    rm -f "$PID_PATH"
  else
    # 兜底:按命令行特征杀
    pkill -f "run --path $DB_PATH --host $HOST --port $PORT" 2>/dev/null \
      && echo "已按命令行匹配停止" || echo "未发现运行中的后端"
  fi
}

status() {
  if _running; then
    echo "运行中:http://$HOST:$PORT"
    [ -f "$PID_PATH" ] && echo "pid=$(cat "$PID_PATH")"
    return 0
  else
    echo "未运行"
    return 0
  fi
}

case "${1:-status}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; sleep 1; start ;;
  status)  status ;;
  *) echo "用法: $0 {start|stop|restart|status}" >&2; exit 1 ;;
esac
