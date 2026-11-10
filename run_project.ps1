$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "         PREDRIVE AI - FULLSTACK LAUNCHER                " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Check Python Venv
$pythonExe = if (Test-Path "$root\.venv\Scripts\python.exe") {
    "$root\.venv\Scripts\python.exe"
} elseif (Test-Path "$root\venv\Scripts\python.exe") {
    "$root\venv\Scripts\python.exe"
} else {
    "python"
}

# Get local IP for Phone access
$localIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { 
    $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and ($_.InterfaceAlias -like "*Wi-Fi*" -or $_.InterfaceAlias -like "*Ethernet*") 
} | Select-Object -First 1 -ExpandProperty IPAddress)
if (-not $localIp) { $localIp = "127.0.0.1" }

# 1. Start Backend + AI (Port 8000)
Write-Host "`n[1/2] Starting Backend Gateway (FastAPI + AI)..." -ForegroundColor Yellow
$port8000Process = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
if ($port8000Process) {
    Write-Host "  -> Port 8000 đang được dùng bởi PID $port8000Process. Đang khởi động lại..." -ForegroundColor Gray
    Stop-Process -Id $port8000Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

$backendCmd = "cd '$root'; `$env:PYTHONPATH = '$root'; & '$pythonExe' -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd

Start-Sleep -Seconds 2

# 2. Start Frontend PWA (Port 5173 - HTTPS)
Write-Host "[2/2] Starting Frontend Cockpit PWA (HTTPS)..." -ForegroundColor Yellow
$port5173Process = Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
if ($port5173Process) {
    Write-Host "  -> Port 5173 đang được dùng bởi PID $port5173Process. Đang giải phóng..." -ForegroundColor Gray
    Stop-Process -Id $port5173Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

$frontendCmd = "cd '$root\frontend'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd

Write-Host "`nServices started in separate PowerShell windows:" -ForegroundColor Green
Write-Host "  PC Web:   https://localhost:5173/" -ForegroundColor White
Write-Host "  Admin UI: https://localhost:5173/?view=admin" -ForegroundColor White
Write-Host "  Swagger:  http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host "  Phone:    https://$($localIp):5173/" -ForegroundColor Cyan
