# Build portable Windows executable for DODA Tracker
# Run from PowerShell:
#   cd C:\Users\jordi\.openclaw\workspace\doda_tracker
#   powershell -ExecutionPolicy Bypass -File .\build_exe.ps1

$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

# Ensure venv exists (Python 3.12 recommended)
if (!(Test-Path ".\.venv\Scripts\python.exe")) {
  Write-Host "Missing .venv. Create it with Python 3.12 first." -ForegroundColor Red
  exit 1
}

# Install build deps
.\.venv\Scripts\python.exe -m pip install --upgrade pip pyinstaller

# Build
.\.venv\Scripts\pyinstaller.exe --noconsole --name "DODA-Tracker" --onedir `
  --add-data "config.json;." `
  --add-data "status_map.json;." `
  app.py

# Copy config files into dist folder for portability
Copy-Item -Force .\config.json .\dist\DODA-Tracker\config.json
Copy-Item -Force .\status_map.json .\dist\DODA-Tracker\status_map.json

Write-Host "Build output: $PSScriptRoot\dist\DODA-Tracker" -ForegroundColor Green
