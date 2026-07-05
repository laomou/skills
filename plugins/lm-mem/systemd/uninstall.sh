#!/usr/bin/env bash
# 卸载 lm-mem systemd 用户服务。
#   ./uninstall.sh
set -euo pipefail

SYS_DIR="$HOME/.config/systemd/user"

remove_svc() {
    local name="$1"
    systemctl --user stop "$name.service" 2>/dev/null || true
    systemctl --user disable "$name.service" 2>/dev/null || true
    rm -f "$SYS_DIR/$name.service"
    echo "✓ 已移除 $name.service"
}

remove_svc "lm-mem-web"
remove_svc "lm-mem-backend"
systemctl --user daemon-reload