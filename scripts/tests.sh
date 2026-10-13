#!/usr/bin/env bash
# 运行全部测试（含 FFmpeg 真实 smoke test）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/_venv.sh"
resolve_python
exec "$PY" -m pytest tests/ -v "$@"
