#!/usr/bin/env bash
# greet.sh — platform-aware greeting script for the hello-script skill
set -euo pipefail

echo "Hello from hello-script!"
echo "  OS:       $(uname -s)"
echo "  Hostname: $(hostname)"
echo "  Date:     $(date)"
