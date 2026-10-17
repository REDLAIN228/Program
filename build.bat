@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
call run.bat --build %*
set "ANIME_BUILD_EXIT=%errorlevel%"
popd
exit /b %ANIME_BUILD_EXIT%
