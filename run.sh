#!/bin/bash
# 可选：从 .env 读取配置（.env 已被 gitignore，不要提交）
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
exec python3 -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}
