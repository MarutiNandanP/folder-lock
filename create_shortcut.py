"""
create_shortcut.py - Creates Windows Desktop and Start Menu shortcuts for FolderLock.
"""

import os
import sys
import subprocess
from pathlib import Path


def create_shortcuts() -> bool:
    if sys.platform != "win32":
        print("Shortcuts can only be created on Windows.")
        return False

    script_dir = Path(__file__).parent.resolve()
    bat_target = script_dir / "FolderLock.bat"
    icon_path = Path(os.environ.get("LOCALAPPDATA", "")) / "FolderLock" / "app_icon.ico"
    if not icon_path.exists():
        # Fallback to pythonw icon
        icon_path = Path(sys.executable).parent / "pythonw.exe"

    ps_script = f"""
    $WshShell = New-Object -comObject WScript.Shell

    # 1. Desktop Shortcut
    $Desktop = [Environment]::GetFolderPath('Desktop')
    $DeskShortcut = $WshShell.CreateShortcut("$Desktop\\FolderLock.lnk")
    $DeskShortcut.TargetPath = "{str(bat_target)}"
    $DeskShortcut.WorkingDirectory = "{str(script_dir)}"
    $DeskShortcut.IconLocation = "{str(icon_path)}"
    $DeskShortcut.Description = "FolderLock - Military-Grade AES-256 Folder Vault"
    $DeskShortcut.Save()
    Write-Output "Created: $Desktop\\FolderLock.lnk"

    # 2. Start Menu Programs Shortcut
    $StartMenu = [Environment]::GetFolderPath('Programs')
    if (Test-Path $StartMenu) {{
        $StartShortcut = $WshShell.CreateShortcut("$StartMenu\\FolderLock.lnk")
        $StartShortcut.TargetPath = "{str(bat_target)}"
        $StartShortcut.WorkingDirectory = "{str(script_dir)}"
        $StartShortcut.IconLocation = "{str(icon_path)}"
        $StartShortcut.Description = "FolderLock - Military-Grade AES-256 Folder Vault"
        $StartShortcut.Save()
        Write-Output "Created: $StartMenu\\FolderLock.lnk"
    }}
    """

    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True
        )
        print(res.stdout)
        if res.returncode == 0:
            print("[+] FolderLock desktop shortcut created successfully!")
            return True
        else:
            print(f"[-] PowerShell error: {res.stderr}")
            return False
    except Exception as e:
        print(f"[-] Failed to create shortcut: {e}")
        return False


if __name__ == "__main__":
    create_shortcuts()
