@echo off
setlocal
cd /d "%~dp0"
set "ANIME_DRAWER_NO_PAUSE=1"
call run.bat --install-only
if errorlevel 1 goto failed
.venv-win\Scripts\python.exe -m pip install -r requirements-dev.txt
if errorlevel 1 goto failed
set QT_QPA_PLATFORM=offscreen
.venv-win\Scripts\python.exe -m pytest -q
if errorlevel 1 goto failed
set QT_QPA_PLATFORM=
.venv-win\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name AnimeDrawer --icon assets\anime-drawer.ico --collect-all mss --collect-all keyring --hidden-import keyring.backends.Windows main.py
if errorlevel 1 goto failed
echo.
echo Build complete: dist\AnimeDrawer\AnimeDrawer.exe
echo Distribute the complete dist\AnimeDrawer directory, including _internal.
echo Native input and Roblox acceptance still require testing on the target Windows PC.
endlocal
exit /b 0

:failed
set "ANIME_BUILD_EXIT=%errorlevel%"
echo.
echo Build failed. Read the error above.
pause
exit /b %ANIME_BUILD_EXIT%
