@echo off
setlocal enabledelayedexpansion
title FolderLock Uninstaller

echo ========================================================
echo        FolderLock - Application Uninstaller
echo ========================================================
echo.
echo Are you sure you want to uninstall FolderLock from this computer?
echo (Note: Any folders that are currently locked will remain safely encrypted.)
echo.
set /p "CONFIRM=Type Y to proceed or N to cancel: "
if /i not "!CONFIRM!"=="Y" (
    echo [INFO] Uninstallation cancelled by user.
    pause
    exit /b 0
)

:: 1. Define Target Paths
set "INSTALL_DIR=%LOCALAPPDATA%\FolderLock\bin"

:: 2. Stop running instances
echo [*] Stopping running FolderLock processes...
taskkill /f /im FolderLock.exe >nul 2>&1
taskkill /f /im FolderLockService.exe >nul 2>&1
taskkill /f /im FolderLockPrompt.exe >nul 2>&1
taskkill /f /im FolderLockCLI.exe >nul 2>&1
timeout /t 1 /nobreak >nul 2>&1

:: 3. Remove Windows Explorer Context Menu
echo [*] Removing Windows Explorer context menu...
reg delete "HKCU\Software\Classes\Directory\shell\FolderLock" /f >nul 2>&1
echo     [OK] Explorer context menu removed.

:: 4. Remove Windows Startup Run entry
echo [*] Removing Windows startup entry...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "FolderLockService" /f >nul 2>&1
echo     [OK] Startup entry removed.

:: 5. Remove Desktop Shortcut
echo [*] Removing Desktop shortcut...
if exist "%USERPROFILE%\Desktop\FolderLock.lnk" del /f /q "%USERPROFILE%\Desktop\FolderLock.lnk" >nul 2>&1
echo     [OK] Desktop shortcut removed.

:: 6. Remove Start Menu Shortcut
echo [*] Removing Start Menu shortcut...
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\FolderLock.lnk" del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\FolderLock.lnk" >nul 2>&1
echo     [OK] Start Menu shortcut removed.

:: 7. Remove Application Binaries
echo [*] Removing installed files in %INSTALL_DIR%...
if exist "%INSTALL_DIR%" (
    rd /s /q "%INSTALL_DIR%" >nul 2>&1
)
echo     [OK] Application files removed.

echo.
echo ========================================================
echo        FolderLock has been successfully uninstalled.
echo ========================================================
echo.
pause
