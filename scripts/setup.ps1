# 一键初始化：创建虚拟环境并安装锁定依赖
# 用法：在项目根目录执行  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

if (-not (Test-Path ".venv")) {
    Write-Host ">> 创建虚拟环境 .venv" -ForegroundColor Cyan
    py -3.14 -m venv .venv
    if ($LASTEXITCODE -ne 0) { py -m venv .venv }
}
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ">> 已生成 .env，请填入 LLM_API_KEY / GITHUB_TOKEN" -ForegroundColor Yellow
}

Write-Host ">> 依赖安装完成。FFmpeg 请用 winget install Gyan.FFmpeg 或确认 PATH 可用。" -ForegroundColor Green
& $py -m videoforge.cli check --no-ping
