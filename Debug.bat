@echo off
setlocal

REM Backward-compatible wrapper for local deployment.
call "%~dp0Debug-Local.bat"
exit /b %errorlevel%