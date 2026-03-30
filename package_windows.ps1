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

Write-Step "Installing Playwright (driver only, no bundled browsers)"
& .\.venv\Scripts\pip install -r requirements.txt pyinstaller > $null

Write-Step "Running PyInstaller"
$specArgs = @(
    '--noconfirm',
    '--clean',
    '--onefile',
    '--windowed',
    '--name', 'dashboard_runner',
    '--distpath', $OutputDir,
    '--add-data', 'index_example.html;.',
    'run_universal.py'
)

& .\.venv\Scripts\pyinstaller @specArgs

Write-Step "Packaging complete. EXE located at $OutputDir\dashboard_runner.exe"
Write-Step "Note: requires Chrome or Edge installed on target machine."
