param(
    [string]$OutputDir = 'dist'
)

$ErrorActionPreference = 'Stop'

if ($MyInvocation.InvocationName -ne '.') {
    Write-Host "[build] 提示：请使用 PowerShell 调用此脚本，例如：powershell -ExecutionPolicy Bypass -File package_windows.ps1" -ForegroundColor Yellow
}

function Write-Step($text) {
    Write-Host "[build] $text" -ForegroundColor Cyan
}

Write-Step "Cleaning previous build output"
Remove-Item -Recurse -Force $OutputDir -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue

Write-Step "Installing dependencies"
if (-not (Test-Path .venv)) {
    python -m venv .venv
}
& .\.venv\Scripts\pip install --upgrade pip > $null
& .\.venv\Scripts\pip install -r requirements.txt pyinstaller > $null

Write-Step "Installing Playwright browsers"
& .\.venv\Scripts\python -m playwright install chromium msedge > $null

Write-Step "Running PyInstaller"
$specArgs = @(
    '--noconfirm',
    '--onefile',
    '--console',
    '--name', 'dashboard_runner',
    'run_universal.py'
)

& .\.venv\Scripts\pyinstaller @specArgs

Write-Step "Copying bundled Playwright browsers"
$pwSrc = Join-Path (Resolve-Path '.\.venv\Scripts\..\') 'Lib\site-packages\playwright\driver\package\win64'
$pwDest = Join-Path $OutputDir 'ms-playwright'
robocopy $pwSrc $pwDest /E > $null

Write-Step "Packaging complete. EXE located at $OutputDir\dashboard_runner.exe"
