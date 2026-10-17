@echo off
setlocal
set "ANIME_START_EXIT=1"
pushd "%~dp0"
if errorlevel 1 goto folder_error
if not exist bootstrap.py goto missing_files

rem Prefer the existing environment, then supported installed interpreters.
".venv-win\Scripts\python.exe" bootstrap.py --check-python >nul 2>&1
if "%errorlevel%"=="0" goto use_venv
py -3.11 bootstrap.py --check-python >nul 2>&1
if "%errorlevel%"=="0" goto use_py311
py -3.12 bootstrap.py --check-python >nul 2>&1
if "%errorlevel%"=="0" goto use_py312
py -3.13 bootstrap.py --check-python >nul 2>&1
if "%errorlevel%"=="0" goto use_py313
python bootstrap.py --check-python >nul 2>&1
if "%errorlevel%"=="0" goto use_python
python3 bootstrap.py --check-python >nul 2>&1
if "%errorlevel%"=="0" goto use_python3

echo.
echo ANIME DRAWER could not find a supported Python installation.
echo Install Python 3.11, 3.12 or 3.13, 64-bit, from https://www.python.org/
echo Enable the Python Launcher or Add python.exe to PATH during installation.
echo Python 3.14+ and 32-bit Python cannot run these pinned dependencies.
if not exist logs mkdir logs
echo No compatible Python 3.11-3.13 x64 was found.>> "logs\startup.log"
goto failed

:use_venv
".venv-win\Scripts\python.exe" -X utf8 -u bootstrap.py %*
goto finished
:use_py311
py -3.11 -X utf8 -u bootstrap.py %*
goto finished
:use_py312
py -3.12 -X utf8 -u bootstrap.py %*
goto finished
:use_py313
py -3.13 -X utf8 -u bootstrap.py %*
goto finished
:use_python
python -X utf8 -u bootstrap.py %*
goto finished
:use_python3
python3 -X utf8 -u bootstrap.py %*
goto finished

:finished
set "ANIME_START_EXIT=%errorlevel%"
if not "%ANIME_START_EXIT%"=="0" goto failed
popd
exit /b 0

:missing_files
echo.
echo Missing bootstrap.py. Extract the COMPLETE ZIP into a folder first.
echo run.bat must be next to bootstrap.py, main.py, requirements.txt and app.
goto failed

:failed
echo.
echo ANIME DRAWER did not start. Read the error above.
echo If available, the details are saved in logs\startup.log in this folder.
if not "%ANIME_DRAWER_NO_PAUSE%"=="1" pause
popd
exit /b %ANIME_START_EXIT%

:folder_error
echo Could not open the program folder. Extract the ZIP to a local folder.
if not "%ANIME_DRAWER_NO_PAUSE%"=="1" pause
exit /b 1
