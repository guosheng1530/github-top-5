#!/usr/bin/env bash
# Demo 闭环：真实 GitHub 数据 + 中文旁白 + FFmpeg 成片，零 LLM 费用
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/_venv.sh"
resolve_python
exec "$PY" -m videoforge.cli demo "$@"
