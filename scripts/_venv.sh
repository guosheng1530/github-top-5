# 共享：跨平台解析虚拟环境里的 Python 解释器。
# 这是一个 **被 source** 的辅助文件，不单独执行。使用方式：
#   source "$(dirname "${BASH_SOURCE[0]}")/_venv.sh"
#   resolve_python          # 设置全局变量 PY，失败时退出
#   "$PY" -m videoforge.cli ...
#
# 为什么需要它？
#   不同操作系统 / 不同创建方式下，venv 里 python 的位置不一样：
#     * Linux/macOS 原生 venv ：  .venv/bin/python
#     * Windows 原生 venv     ：  .venv/Scripts/python.exe
#     * 本仓库历史遗留         ：  .venv 是从 Windows 机器提交进来的（含 Scripts/，
#                                无 bin/），真正的 Linux venv 另建在 .venv-linux/
#   旧脚本把路径写死成 .venv/bin/python，于是在 Linux 上必然 "No such file or
#   directory"。这里按优先级探测所有已知布局，彻底解决跨平台启动问题。

# 解析可用的 venv Python 到全局变量 PY。
# 查找顺序：
#   1. .venv/bin/python          （POSIX 原生 venv，最常见）
#   2. .venv-linux/bin/python    （Linux 回退：.venv 是提交进来的 Windows venv 时）
#   3. .venv/Scripts/python.exe  （Windows venv，在 Git Bash / WSL 下也可被 bash 调用）
#   4. 系统 python3 / python     （没有 venv 时的最后兜底，仅给出提示）
resolve_python() {
    local root="${ROOT:?resolve_python 需要先设置 ROOT 变量}"
    local candidates=(
        "$root/.venv/bin/python"
        "$root/.venv-linux/bin/python"
        "$root/.venv/Scripts/python.exe"
    )
    for c in "${candidates[@]}"; do
        if [ -x "$c" ]; then
            PY="$c"
            return 0
        fi
    done
    # 兜底：系统 Python（提示用户先 setup，便于诊断“为什么没走 venv”）
    local sys_py
    sys_py="$(command -v python3 || command -v python || true)"
    if [ -n "$sys_py" ]; then
        echo "⚠️  未找到项目虚拟环境（.venv / .venv-linux）；" >&2
        echo "    回退到系统 Python：$sys_py" >&2
        echo "    建议先运行：bash scripts/setup.sh" >&2
        PY="$sys_py"
        return 0
    fi
    echo "❌ 既没有虚拟环境，也找不到系统 python3/python。请先安装 Python 3.10+。" >&2
    return 1
}
