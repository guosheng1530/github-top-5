# 正式生成：火山方舟文本 + GitHub 数据 + SAPI 旁白 -> 约 5 分钟中文 MP4
# 中断后可恢复：  powershell -File scripts\run.ps1 --resume
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
. "$PSScriptRoot\_venv.ps1"
$py = Resolve-Python
& $py -m videoforge.cli run @args
