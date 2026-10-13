# 正式生成：火山方舟文本 + GitHub 数据 + SAPI 旁白 -> 约 5 分钟中文 MP4
# 中断后可用  -Resume ？当前 CLI 参数为 --resume：
#   powershell -File scripts\run.ps1 --resume
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
.\.venv\Scripts\python.exe -m videoforge.cli run @args
