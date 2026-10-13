# 启动本地任务 API（默认 127.0.0.1:8765，文档 /docs）
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
. "$PSScriptRoot\_venv.ps1"
$py = Resolve-Python
& $py -m videoforge.cli serve @args
