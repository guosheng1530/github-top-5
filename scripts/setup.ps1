# 一键初始化：创建虚拟环境并安装锁定依赖
# 用法：在项目根目录执行  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

# 决定在哪里建 venv。正常用 .venv；但若 .venv 是从 Linux 机器拷来的
# （只有 bin/，没有 Scripts/），在 Windows 上不可用，改建 .venv-windows。
$VenvDir = ".venv"
if ((Test-Path ".venv") -and -not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host ">> 检测到 .venv 不是 Windows 虚拟环境（可能来自 Linux），改用 .venv-windows" -ForegroundColor Yellow
    $VenvDir = ".venv-windows"
}

if (-not (Test-Path "$VenvDir\Scripts\python.exe")) {
    Write-Host ">> 创建虚拟环境 $VenvDir" -ForegroundColor Cyan
    py -3.14 -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { py -m venv $VenvDir }
}
$py = ".\$VenvDir\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ">> 已生成 .env，请填入 LLM_API_KEY / GITHUB_TOKEN" -ForegroundColor Yellow
}

Write-Host ">> 依赖安装完成。FFmpeg 请用 winget install Gyan.FFmpeg 或确认 PATH 可用。" -ForegroundColor Green
& $py -m videoforge.cli check --no-ping
