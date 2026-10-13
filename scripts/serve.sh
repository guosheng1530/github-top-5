#!/usr/bin/env bash
# 启动本地任务 API（默认 127.0.0.1:8765，文档 /docs）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/_venv.sh"
resolve_python
exec "$PY" -m videoforge.cli serve "$@"
