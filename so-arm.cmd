@echo off
setlocal
set "PYTHONUTF8=1"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Project Python is missing. Run the Windows installation first.
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0windows\so_arm.py" %*
exit /b %errorlevel%
