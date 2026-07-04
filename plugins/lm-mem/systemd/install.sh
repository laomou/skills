#!/usr/bin/env bash
# 安装 lm-mem systemd 用户服务。
#
#   ./install.sh              安装并启用(不启动)
#   ./install.sh start        安装、启用、启动
#   ./install.sh remove        卸载服务

set -euo pipefail

SYSTEMD_DIR="$HOME/.config/systemd/user"
SVC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

install_service() {
    local name="$1"
    cp "$SVC_DIR/$name.service" "$SYSTEMD_DIR/"
    systemctl --user daemon-reload
    systemctl --user enable "$name.service"
    echo "✓ 已安装并启用 $name.service"
}

remove_service() {
    local name="$1"
    systemctl --user stop "$name.service" 2>/dev/null || true
    systemctl --user disable "$name.service" 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/$name.service"
    echo "✓ 已移除 $name.service"
}

case "${1:-install}" in
    install|start)
        mkdir -p "$SYSTEMD_DIR"
        install_service "lm-mem-backend"
        install_service "lm-mem-web"
        systemctl --user daemon-reload
        if [ "$1" = "start" ]; then
            systemctl --user start lm-mem-backend.service lm-mem-web.service
            echo "✓ 已启动"
        fi
        ;;
    remove)
        remove_service "lm-mem-web"
        remove_service "lm-mem-backend"
        systemctl --user daemon-reload
        ;;
    *)
        echo "用法: $0 [install|start|remove]"
        exit 1
        ;;
esac