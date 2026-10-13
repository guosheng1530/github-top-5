# 共享：跨平台解析虚拟环境里的 Python 解释器（PowerShell 版）。
# 这是一个 **被 dot-source** 的辅助文件，不单独执行。使用方式：
#   . "$PSScriptRoot\_venv.ps1"
#   $py = Resolve-Python          # 返回解释器路径；失败时抛出
#   & $py -m videoforge.cli ...
#
# 为什么需要它？见 scripts/_venv.sh 的说明。Windows 原生 venv 的 python 在
# .venv\Scripts\python.exe；但若仓库是从 Linux 机器拷来的，也可能只有
# .venv/bin/python。这里按优先级探测，并在都没有时回退系统 py/python。

function Resolve-Python {
    $root = Split-Path $PSScriptRoot -Parent
    $candidates = @(
        (Join-Path $root ".venv\Scripts\python.exe"),   # Windows 原生 venv
        (Join-Path $root ".venv-windows\Scripts\python.exe"),
        (Join-Path $root ".venv\bin\python"),            # POSIX 布局（混合检出）
        (Join-Path $root ".venv-linux\bin\python")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    # 兜底：系统 Python
    $sys = Get-Command py -ErrorAction SilentlyContinue
    if ($sys) { 
        Write-Host "⚠️  未找到项目虚拟环境，回退系统 py。建议先运行 scripts\setup.ps1" -ForegroundColor Yellow
        return "py" 
    }
    $sys = Get-Command python -ErrorAction SilentlyContinue
    if ($sys) {
        Write-Host "⚠️  未找到项目虚拟环境，回退系统 python。建议先运行 scripts\setup.ps1" -ForegroundColor Yellow
        return "python"
    }
    throw "❌ 既没有虚拟环境，也找不到系统 py/python。请先安装 Python 3.10+。"
}
