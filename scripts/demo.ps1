# Demo 闭环：真实 GitHub 数据 + SAPI 中文旁白 + FFmpeg 成片，零 LLM 费用
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
. "$PSScriptRoot\_venv.ps1"
$py = Resolve-Python
& $py -m videoforge.cli demo @args
