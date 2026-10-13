#!/usr/bin/env bash
# 环境与能力核查（会发一次最小真实 LLM 请求；加 --no-ping 可跳过）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/_venv.sh"
resolve_python
exec "$PY" -m videoforge.cli check "$@"
