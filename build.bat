@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11 x64 from python.org, including the Python launcher.
  exit /b 1
)
if not exist .venv-win\Scripts\python.exe (
  py -3.11 -m venv .venv-win
  if errorlevel 1 exit /b 1
)
.venv-win\Scripts\python.exe -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'"
if errorlevel 1 exit /b 1
.venv-win\Scripts\python.exe -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b 1
set QT_QPA_PLATFORM=offscreen
.venv-win\Scripts\python.exe -m pytest -q
if errorlevel 1 exit /b 1
set QT_QPA_PLATFORM=
.venv-win\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name AnimeDrawer --icon assets\anime-drawer.ico --collect-all mss --collect-all keyring --hidden-import keyring.backends.Windows main.py
if errorlevel 1 exit /b 1
echo.
echo Build complete: dist\AnimeDrawer\AnimeDrawer.exe
echo Distribute the complete dist\AnimeDrawer directory, including _internal.
echo Native input and Roblox acceptance still require testing on the target Windows PC.
endlocal
