#!/usr/bin/env bash
# 安装 lm-mem systemd 用户服务(安装+启用,不启动)。
set -euo pipefail

SVC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYS_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYS_DIR"

for name in lm-mem-backend lm-mem-web; do
    cp "$SVC_DIR/$name.service" "$SYS_DIR/"
    systemctl --user enable "$name.service"
    echo "✓ $name.service"
done
systemctl --user daemon-reload
echo "已安装。启动: systemctl --user start lm-mem-backend lm-mem-web"