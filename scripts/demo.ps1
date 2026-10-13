# Demo 闭环：真实 GitHub 数据 + SAPI 中文旁白 + FFmpeg 成片，零 LLM 费用
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
.\.venv\Scripts\python.exe -m videoforge.cli demo @args
