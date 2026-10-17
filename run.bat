@echo off
setlocal
cd /d "%~dp0"
if not exist .venv-win\Scripts\python.exe (
  py -3.11 -m venv .venv-win
  if errorlevel 1 exit /b 1
  .venv-win\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 exit /b 1
)
.venv-win\Scripts\python.exe main.py %*
endlocal
