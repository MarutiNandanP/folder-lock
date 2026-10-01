@echo off
setlocal enabledelayedexpansion
title FolderLock Installation Setup

echo ========================================================
echo        FolderLock - Professional Folder Encryption
echo        Automated Windows Installation Setup
echo ========================================================
echo.

:: 1. Define Target Paths
set "INSTALL_DIR=%LOCALAPPDATA%\FolderLock\bin"
set "SOURCE_DIR=%~dp0bin"

echo [*] Target Directory : %INSTALL_DIR%
echo [*] Source Directory : %SOURCE_DIR%
echo.

:: 2. Verify source directory exists
if not exist "%SOURCE_DIR%\FolderLock.exe" (
    echo [ERROR] Installation binaries not found in:
    echo         %SOURCE_DIR%
    echo Please make sure the 'bin' folder exists with all executable files.
    pause
    exit /b 1
)

:: 3. Terminate any running instances of FolderLock
echo [*] Terminating any currently running FolderLock instances...
taskkill /f /im FolderLock.exe >nul 2>&1
taskkill /f /im FolderLockService.exe >nul 2>&1
taskkill /f /im FolderLockPrompt.exe >nul 2>&1
taskkill /f /im FolderLockCLI.exe >nul 2>&1
timeout /t 1 /nobreak >nul 2>&1

:: 4. Create installation directory
echo [*] Creating installation folder...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

:: 5. Copy all files
echo [*] Copying application binaries...
xcopy /y /e /q "%SOURCE_DIR%\*" "%INSTALL_DIR%\" >nul
if errorlevel 1 (
    echo [ERROR] Failed to copy files to %INSTALL_DIR%.
    pause
    exit /b 1
)
echo     [OK] Binaries installed successfully.

:: 6. Register Windows Explorer Right-Click Context Menu
echo [*] Registering Windows Explorer context menu ("Lock / Unlock with FolderLock")...
reg add "HKCU\Software\Classes\Directory\shell\FolderLock" /ve /t REG_SZ /d "Lock / Unlock with FolderLock" /f >nul
reg add "HKCU\Software\Classes\Directory\shell\FolderLock" /v "Icon" /t REG_SZ /d "\"%INSTALL_DIR%\FolderLockPrompt.exe\",0" /f >nul
reg add "HKCU\Software\Classes\Directory\shell\FolderLock\command" /ve /t REG_SZ /d "\"%INSTALL_DIR%\FolderLockPrompt.exe\" \"%%1\"" /f >nul
echo     [OK] Explorer context menu registered.

:: 7. Register Background Guard Service at Windows Startup
echo [*] Registering FolderLock 24/7 background guard service at Windows startup...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "FolderLockService" /t REG_SZ /d "\"%INSTALL_DIR%\FolderLockService.exe\"" /f >nul
echo     [OK] Windows autostart configured.

:: 8. Create Desktop Shortcut
echo [*] Creating Desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%USERPROFILE%\Desktop\FolderLock.lnk'); $s.TargetPath = '%INSTALL_DIR%\FolderLock.exe'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.IconLocation = '%INSTALL_DIR%\FolderLock.exe,0'; $s.Description = 'FolderLock - AES-256 Folder Encryption & AutoLock'; $s.Save()" >nul 2>&1
echo     [OK] Desktop shortcut created.

:: 9. Create Start Menu Shortcut
echo [*] Creating Start Menu shortcut...
set "START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%START_MENU%\FolderLock.lnk'); $s.TargetPath = '%INSTALL_DIR%\FolderLock.exe'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.IconLocation = '%INSTALL_DIR%\FolderLock.exe,0'; $s.Description = 'FolderLock - AES-256 Folder Encryption & AutoLock'; $s.Save()" >nul 2>&1
echo     [OK] Start Menu shortcut created.

:: 10. Start the 24/7 Background Service
echo [*] Starting FolderLock Background Guard Service...
start "" "%INSTALL_DIR%\FolderLockService.exe"
echo     [OK] Background Service is running.

:: 11. Launch the Main GUI
echo [*] Launching FolderLock Application...
start "" "%INSTALL_DIR%\FolderLock.exe"

echo.
echo ========================================================
echo        [SUCCESS] FolderLock Installation Complete!
echo ========================================================
echo.
echo Quick Start Guide:
echo 1. Right-click ANY folder in Windows Explorer and select:
echo    "Lock / Unlock with FolderLock"
echo 2. Open FolderLock anytime from your Desktop or Start Menu.
echo 3. The 24/7 background guard service is now active and will
echo    automatically protect your locked vaults on idle or Win+L.
echo.
pause
