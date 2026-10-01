@echo off
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] ADMINISTRATOR PRIVILEGES REQUIRED
    echo Please right-click this file and select 'Run as Administrator'.
    pause
    exit /b 1
)

echo [*] Stopping and removing 'FolderLock' from Windows Services (services.msc)...
python "c:\folderlock\folderlock_win_service.py" stop
python "c:\folderlock\folderlock_win_service.py" remove
echo.
echo [+] FolderLock removed from Windows Services.
pause
