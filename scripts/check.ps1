# 环境与能力核查（会发一次最小真实 LLM 请求；加 --no-ping 可跳过）
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
. "$PSScriptRoot\_venv.ps1"
$py = Resolve-Python
& $py -m videoforge.cli check @args
