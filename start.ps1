# OrbitScope Unified Startup Script (PowerShell)
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Starting OrbitScope Astronomical Platform" -ForegroundColor Cyan
Write-Host "  SPHEREx Time-Domain Sky Monitoring & Detection" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

$root = $PSScriptRoot

Write-Host "[1/2] Starting OrbitScope Backend on http://localhost:8000 ..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; python run.py"

Start-Sleep -Seconds 3

Write-Host "[2/2] Starting OrbitScope Frontend on http://localhost:5173 ..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"

Write-Host ""
Write-Host "OrbitScope processes launched successfully!" -ForegroundColor Yellow
Write-Host "Frontend:    http://localhost:5173" -ForegroundColor White
Write-Host "Backend API: http://localhost:8000" -ForegroundColor White
Write-Host "API Docs:    http://localhost:8000/docs" -ForegroundColor White
