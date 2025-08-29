@echo off
call "C:\Program Files\QGIS 3.40.4\bin\o4w_env.bat"
call "C:\Program Files\QGIS 3.40.4\etc\ini\qt5.bat"
call "C:\Program Files\QGIS 3.40.4\etc\ini\python3.bat"

@echo on
pyrcc5 -o resources.py resources.qrc