@echo off
echo ========================================================
echo   Starting OrbitScope Platform (Backend + Frontend)
echo   SPHEREx Time-Domain Sky Monitoring System
echo ========================================================
echo.

cd /d "%~dp0backend"
echo [1/2] Starting OrbitScope Python Backend on http://localhost:8000 ...
start "OrbitScope Backend" python run.py

timeout /t 3 /nobreak >nul

cd /d "%~dp0frontend"
echo [2/2] Starting OrbitScope React Frontend on http://localhost:5173 ...
start "OrbitScope Frontend" npm run dev

echo.
echo ========================================================
echo   OrbitScope is starting!
echo   Frontend: http://localhost:5173
echo   Backend API: http://localhost:8000
echo   API Docs: http://localhost:8000/docs
echo ========================================================
echo.
pause
