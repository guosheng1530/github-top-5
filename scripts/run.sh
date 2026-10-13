#!/usr/bin/env bash
# 正式生成：火山方舟文本 + GitHub 数据 + 旁白 -> 约 5 分钟中文 MP4
# 中断后可恢复：  ./scripts/run.sh --resume
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/_venv.sh"
resolve_python
exec "$PY" -m videoforge.cli run "$@"
