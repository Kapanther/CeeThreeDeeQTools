@echo off
setlocal

REM Define source and destination paths
set "source=.\CeeThreeDeeQTools"
set "destination3=%appdata%\QGIS\QGIS3\profiles\default\python\plugins\CeeThreeDeeQTools"
set "destination4=%appdata%\QGIS\QGIS4\profiles\default\python\plugins\CeeThreeDeeQTools"

echo Deploying plugin from "%source%"

echo.
echo --- Deploy to QGIS 3 ---
if not exist "%destination3%" (
    mkdir "%destination3%"
)
robocopy "%source%" "%destination3%" /MIR /E /R:3 /W:5
if %errorlevel% geq 8 (
    echo Error occurred during QGIS 3 file copy.
    exit /b %errorlevel%
)
echo QGIS 3 files copied successfully.

echo.
echo --- Deploy to QGIS 4 ---
if not exist "%destination4%" (
    mkdir "%destination4%"
)
robocopy "%source%" "%destination4%" /MIR /E /R:3 /W:5
if %errorlevel% geq 8 (
    echo Error occurred during QGIS 4 file copy.
    exit /b %errorlevel%
)
echo QGIS 4 files copied successfully.

echo.
echo Deployment complete.
exit /b 0
