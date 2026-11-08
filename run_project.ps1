$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "         PREDRIVE AI - FULLSTACK LAUNCHER                " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Start Backend + AI (Port 8000)
Write-Host "`n[1/2] Starting Backend Gateway (FastAPI + AI)..." -ForegroundColor Yellow
$backendCmd = "cd '$root'; `$env:PYTHONPATH = '$root'; .\venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd

Start-Sleep -Seconds 3

# 2. Start Frontend PWA (Port 5173 - HTTPS)
Write-Host "[2/2] Starting Frontend Cockpit PWA (HTTPS)..." -ForegroundColor Yellow
$frontendCmd = "cd '$root\frontend'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd

Write-Host "`nServices started in separate PowerShell windows:" -ForegroundColor Green
Write-Host "  PC:     https://localhost:5173/" -ForegroundColor White
Write-Host "  Phone:  https://192.168.0.106:5173/" -ForegroundColor White
