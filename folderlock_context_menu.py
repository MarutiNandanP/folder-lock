"""
folderlock_context_menu.py - Windows Explorer Right-Click Context Menu Integrator.

Installs or removes:
- "Lock with FolderLock" / "Unlock with FolderLock" in Windows Explorer context menu.
Operates on HKEY_CURRENT_USER (No Administrator privileges required).
"""

import os
import sys
import winreg
from pathlib import Path


def get_command_string() -> str:
    """Returns the executable command line string for context menu invocation."""
    script_path = Path(__file__).parent / "folderlock_context_dispatcher.py"
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    exe = str(pythonw) if pythonw.exists() else sys.executable
    return f'"{exe}" "{script_path}" "%1"'


def install_context_menu() -> bool:
    """Installs FolderLock in Windows Explorer folder right-click context menu."""
    if sys.platform != "win32":
        print("Context menu is only supported on Windows.")
        return False

    cmd_str = get_command_string()
    icon_str = sys.executable

    try:
        # Register for folder context menu
        key_path = r"Software\Classes\Directory\shell\FolderLock"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Lock / Unlock with FolderLock")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_str)

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, cmd_str)

        print("[+] Explorer context menu installed successfully for current user.")
        return True
    except Exception as e:
        print(f"[-] Failed to install context menu: {e}")
        return False


def uninstall_context_menu() -> bool:
    """Removes FolderLock from Windows Explorer right-click context menu."""
    if sys.platform != "win32":
        return False

    def delete_key_recursive(root, subkey):
        try:
            with winreg.OpenKey(root, subkey, 0, winreg.KEY_ALL_ACCESS) as key:
                while True:
                    try:
                        child = winreg.EnumKey(key, 0)
                        delete_key_recursive(root, subkey + "\\" + child)
                    except OSError:
                        break
            winreg.DeleteKey(root, subkey)
        except FileNotFoundError:
            pass

    try:
        delete_key_recursive(winreg.HKEY_CURRENT_USER, r"Software\Classes\Directory\shell\FolderLock")
        print("[+] Explorer context menu removed successfully.")
        return True
    except Exception as e:
        print(f"[-] Failed to remove context menu: {e}")
        return False


def is_context_menu_installed() -> bool:
    """Checks if context menu is currently registered in Windows registry."""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\Directory\shell\FolderLock\command") as key:
            val, _ = winreg.QueryValueEx(key, "")
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--uninstall":
        uninstall_context_menu()
    else:
        install_context_menu()
