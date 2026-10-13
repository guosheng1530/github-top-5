# 运行全部测试（含 FFmpeg/SAPI 真实 smoke test，约 1-2 分钟）
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
. "$PSScriptRoot\_venv.ps1"
$py = Resolve-Python
& $py -m pytest tests/ -v @args
