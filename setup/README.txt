========================================================================
                      FolderLock v2.0 - AES-256
               Standalone Windows Installer & Setup Package
========================================================================

FolderLock is an enterprise-grade folder encryption and locking utility
designed to protect your confidential files on Windows.

When a folder is locked with FolderLock:
1. Every file and subdirectory is encrypted using AES-256-GCM with a key
   derived via PBKDF2-HMAC-SHA256 (300,000 rounds).
2. Original plaintext files are cryptographically shredded before deletion.
   Even if someone takes your hard drive and connects it to another OS
   (Linux, macOS, Windows PE), they CANNOT view or recover any files without
   your master password.
3. Windows Explorer access to the folder is restricted.
4. A 24/7 background guard service monitors for idle timeouts and Windows
   Workstation Locks (Win + L) to automatically re-lock your sensitive vaults.


========================================================================
HOW TO INSTALL (1-CLICK INSTALLATION)
========================================================================

1. Open this 'setup' folder.
2. Double-click "Install.bat".
3. That's it!

The installer will automatically:
- Copy all application executables to your local user directory:
  %LOCALAPPDATA%\FolderLock\bin
- Add "Lock / Unlock with FolderLock" with an icon to your Windows Explorer
  right-click context menu.
- Create Desktop and Start Menu shortcuts.
- Configure the 24/7 background auto-lock service to start with Windows.
- Launch the background service and open the FolderLock Dashboard.

NO Python installation or third-party dependencies are required on target
computers. Everything is pre-compiled into native Windows binaries.


========================================================================
HOW TO USE FOLDERLOCK
========================================================================

--- Method 1: Right-Click in Windows Explorer (Recommended) ---
- To Lock a folder:
  Right-click any folder -> Select "Lock / Unlock with FolderLock".
  The FolderLock setup window will appear. Enter a master password,
  choose an auto-lock inactivity timer (e.g., 5 min, 15 min, 1 hr, or Never),
  and click "🔒 Lock Folder Now".
  
- To Unlock a folder:
  Right-click the locked folder -> Select "Lock / Unlock with FolderLock".
  A clean password prompt modal will appear on screen. Enter your master
  password and click "Unlock & Open Folder".
  The folder will be decrypted and immediately opened in Windows Explorer.

--- Method 2: FolderLock Desktop Dashboard ---
- Double-click the "FolderLock" shortcut on your Desktop or Start Menu.
- Use the Dashboard to:
  * View all protected vaults and their current lock status.
  * Check live auto-lock countdown timers.
  * One-click "🔒 Lock All Vaults".
  * Control background service status.

--- Method 3: Command Line (CLI) ---
Open Command Prompt and use FolderLockCLI:
  FolderLockCLI.exe lock "C:\Path\To\Folder"
  FolderLockCLI.exe unlock "C:\Path\To\Folder"
  FolderLockCLI.exe status
  FolderLockCLI.exe lock-all


========================================================================
PACKAGE CONTENTS (setup\bin\)
========================================================================

- FolderLock.exe        : Main Graphical Dashboard & Vault Manager.
- FolderLockPrompt.exe  : Lightweight Quick-Unlock password modal.
- FolderLockService.exe : 24/7 background daemon (auto-lock timer & Win+L monitor).
- FolderLockCLI.exe     : Command line interface for advanced users.
- app_icon.ico          : High-resolution application shield icon.
- Install.bat           : Automated 1-click installer.
- Uninstall.bat         : Automated 1-click uninstaller.


========================================================================
HOW TO UNINSTALL
========================================================================

1. Open this 'setup' folder.
2. Double-click "Uninstall.bat".
3. Type 'Y' and press Enter.

The uninstaller will gracefully stop the background guard service, remove
all shortcuts, clean up Windows Explorer context menu entries, remove the
Windows startup entry, and delete installed binaries.
Any locked folders will remain safely encrypted on disk.
========================================================================
