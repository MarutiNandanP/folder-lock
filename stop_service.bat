@echo off
echo Stopping FolderLock Background Service...
python "c:\folderlock\folderlock_cli.py" service stop
echo.
pause
