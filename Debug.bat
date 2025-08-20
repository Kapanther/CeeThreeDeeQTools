@echo off
setlocal

REM Define source and destination paths
set "source=.\CeeThreeDeeQTools"
set "destination=%appdata%\QGIS\QGIS3\profiles\default\python\plugins\CeeThreeDeeQTools"

REM Ensure the destination folder exists
if not exist "%destination%" (
    mkdir "%destination%"
)

REM Use robocopy to copy files and remove any files in the destination that don't exist in the source
robocopy "%source%" "%destination%" /MIR /E /R:3 /W:5

REM Check robocopy exit code
if %errorlevel% geq 8 (
    echo Error occurred during file copy.
    exit /b %errorlevel%
)

echo Files copied successfully.
exit /b 0