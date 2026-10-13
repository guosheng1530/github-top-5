#!/usr/bin/env bash
# 一键初始化（Linux/macOS）：创建虚拟环境并安装锁定依赖
# 用法：在项目根目录执行  bash scripts/setup.sh   或   ./scripts/setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 选一个可用的 python（优先 python3）
PY_BOOT="$(command -v python3 || command -v python || true)"
if [ -z "$PY_BOOT" ]; then
    echo "❌ 未找到 python3/python，请先安装 Python 3.10+" >&2
    exit 1
fi

# 决定在哪里建 venv。
#   正常情况下用 .venv。但本仓库里 .venv 可能是从 Windows 机器提交进来的
#   （只有 Scripts/，没有 bin/）——在 Linux/macOS 上它不可用，也不能往里装包。
#   这种情况下退一步，把原生 venv 建在 .venv-linux/，运行脚本会自动识别。
VENV_DIR=".venv"
if [ -d ".venv" ] && [ ! -x ".venv/bin/python" ]; then
    echo ">> 检测到 .venv 不是本平台可用的虚拟环境（可能来自 Windows），改用 .venv-linux" >&2
    VENV_DIR=".venv-linux"
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo ">> 创建虚拟环境 $VENV_DIR"
    "$PY_BOOT" -m venv "$VENV_DIR"
fi

PY="$ROOT/$VENV_DIR/bin/python"
"$PY" -m pip install --upgrade pip
# requirements.txt 中 pywin32/pyttsx3 带 win32 环境标记，Linux/macOS 自动跳过
"$PY" -m pip install -r requirements.txt

if [ ! -f ".env" ]; then
    cp ".env.example" ".env"
    echo ">> 已生成 .env，请填入 LLM_API_KEY / GITHUB_TOKEN"
fi

echo ">> 依赖安装完成。"
echo ">> 系统依赖请确认已安装："
echo "   Linux: sudo apt install ffmpeg fonts-noto-cjk"
echo "   macOS: brew install ffmpeg   （中文字体系统自带）"

"$PY" -m videoforge.cli check --no-ping
