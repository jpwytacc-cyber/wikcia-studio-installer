@echo off
setlocal
title Wikcia Studio - Windows 11 Setup
echo Wikcia Studio - Desktop, CLI and integrated software
echo Existing application data and accounts will not be replaced.
echo Missing free software will be downloaded. This can take a while.
echo.
set "WIKCIA_BUNDLE=%~dp0."
if not exist "%WIKCIA_BUNDLE%\bootstrap\python\python.exe" set "WIKCIA_BUNDLE=%~dp0bundle\Wikcia-Windows11"
if not exist "%WIKCIA_BUNDLE%\bootstrap\python\python.exe" goto missing_payload
if not exist "%WIKCIA_BUNDLE%\manifest.json" goto missing_payload
if not exist "%WIKCIA_BUNDLE%\installer.py" goto missing_payload
echo Installer payload: "%WIKCIA_BUNDLE%"
"%WIKCIA_BUNDLE%\bootstrap\python\python.exe" -s -u "%~dp0installer.py" --bundle "%WIKCIA_BUNDLE%" %*
set "RESULT=%ERRORLEVEL%"
goto finish
:missing_payload
echo ERROR: The complete installer payload was not found.
echo Checked "%~dp0" and "%~dp0bundle\Wikcia-Windows11".
echo This is a missing-payload error, not proof that the archive is still zipped.
echo Use the complete Wikcia-Complete-Setup package, not a source-only folder.
set "RESULT=1"
:finish
echo.
if "%RESULT%"=="0" echo Requested setup operation completed successfully.
if not "%RESULT%"=="0" echo Setup needs attention. Read the exact error and installation report above.
if not defined WIKCIA_SETUP_NO_PAUSE pause
exit /b %RESULT%
