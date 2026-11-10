@echo off
rem Starts Clipzer on Windows. First run sets everything up.
cd /d "%~dp0"
where ffmpeg >nul 2>nul || (echo Install ffmpeg first:  winget install Gyan.FFmpeg & pause & exit /b 1)
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt
)
if not exist .env copy .env.example .env >nul
echo Clipzer is starting at http://localhost:8000
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
