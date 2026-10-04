$ErrorActionPreference = 'Stop'
$benchdeskRoot = Split-Path -Parent $PSScriptRoot
Push-Location $benchdeskRoot
try {
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $benchdeskRoot 'build\pyinstaller-cache'
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --windowed --onedir --name BenchDesk launch.py
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed' }
    Write-Output 'Built dist\BenchDesk\BenchDesk.exe. Keep the entire BenchDesk folder together.'
} finally {
    Pop-Location
}
