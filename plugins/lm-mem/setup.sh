#!/usr/bin/env bash
# lm-mem 一键安装。
#
# 做三件事:
#   1. 用 uv 同步依赖(.venv)
#   2. 起 Chroma 后端到 8901
#   3. 起 Web UI 到 7531
#
# 完成后:
#   - Web UI: http://127.0.0.1:7531
#   - Claude Code 里 /plugin install lm-mem@laomou-skills 即可
#
# 二次运行:自动跳过已完成的步骤。

set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PLUGIN_DIR"

echo "== 1/3 同步依赖 =="
if [ ! -d ".venv" ]; then
    uv sync
    echo "✓ .venv 已创建"
else
    echo "✓ .venv 已存在,跳过 uv sync"
fi

echo ""
echo "== 2/3 启动后端(8901) =="
./manage.py backend start

echo ""
echo "== 3/3 启动 Web UI(7531) =="
./manage.py web start

echo ""
echo "════════════════════════════════════════"
echo "✓ 安装完成"
echo ""
echo "  Web UI:      http://127.0.0.1:7531"
echo "  管理命令:    ./manage.py {backend|web} {start|stop|restart|status}"
echo ""
echo "  在 Claude Code 中启用:"
echo "    /plugin install lm-mem@laomou-skills"
echo "════════════════════════════════════════"