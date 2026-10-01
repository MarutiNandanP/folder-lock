@echo off
:: Ensure administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ====================================================================
    echo [!] ADMINISTRATOR PRIVILEGES REQUIRED
    echo Windows Service registration requires running this script as Admin.
    echo Please right-click this file and select 'Run as Administrator'.
    echo ====================================================================
    pause
    exit /b 1
)

echo [*] Registering 'FolderLock' in Windows Service Control Manager (services.msc)...
python "c:\folderlock\folderlock_win_service.py" --startup auto install

if %errorlevel% equ 0 (
    echo [+] Successfully registered 'FolderLock' service!
    echo [*] Starting FolderLock service...
    python "c:\folderlock\folderlock_win_service.py" start
    echo.
    echo [+] 'FolderLock' is now installed and RUNNING in services.msc!
    echo You can open 'services.msc' anytime to see 'FolderLock' in the list.
) else (
    echo [-] Failed to install Windows service. See above output.
)

echo.
pause
