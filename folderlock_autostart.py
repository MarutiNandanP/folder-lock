"""
folderlock_autostart.py - Windows Startup Manager for FolderLock Background Service.

Enables/disables running the FolderLock background service automatically
when Windows boots / user logs in.
"""

import os
import sys
import winreg
from pathlib import Path

REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "FolderLockService"


def get_service_command() -> str:
    """Returns the silent execution command for the background service."""
    script_path = Path(__file__).parent / "folderlock_service.py"
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    exe = str(pythonw) if pythonw.exists() else sys.executable
    return f'"{exe}" "{script_path}"'


def is_startup_enabled() -> bool:
    """Checks if background service is set to start with Windows."""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def enable_startup() -> bool:
    """Enables FolderLock background service to start on Windows login."""
    if sys.platform != "win32":
        return False
    try:
        cmd = get_service_command()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        print("[+] FolderLock service registered to start with Windows.")
        return True
    except Exception as e:
        print(f"[-] Failed to enable startup: {e}")
        return False


def disable_startup() -> bool:
    """Disables FolderLock background service from starting on Windows login."""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
        print("[+] FolderLock service startup disabled.")
        return True
    except FileNotFoundError:
        return True
    except Exception as e:
        print(f"[-] Failed to disable startup: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--disable":
        disable_startup()
    else:
        enable_startup()
