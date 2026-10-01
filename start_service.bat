@echo off
echo Starting FolderLock Continuous Background Service...
start "" "C:\Users\Ithra\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe" "c:\folderlock\folderlock_service.py"
timeout /t 2 /nobreak >nul
python "c:\folderlock\folderlock_cli.py" service status
echo.
echo FolderLock Service is now running in the background.
pause
