"""
folderlock_context_dispatcher.py - Smart entry point for Windows Explorer context menu.

If target folder is locked:
  Directly launches compact password prompt modal (folderlock_prompt.py).
If target folder is not locked:
  Launches GUI directly to the Lock tab (folderlock_gui.py --target "%1").
"""

import os
import sys
import subprocess
from pathlib import Path

from folderlock_core import is_folder_locked


def main():
    if len(sys.argv) < 2:
        sys.exit(0)

    target_path = sys.argv[1]
    script_dir = Path(__file__).parent.resolve()
    python_dir = Path(sys.executable).parent
    pythonw = python_dir / "pythonw.exe"
    exe = str(pythonw) if pythonw.exists() else sys.executable

    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW

    if is_folder_locked(target_path):
        # Open quick password modal
        prompt_script = script_dir / "folderlock_prompt.py"
        subprocess.Popen([exe, str(prompt_script), target_path], creationflags=flags)
    else:
        # Open full GUI to lock tab
        gui_script = script_dir / "folderlock_gui.py"
        subprocess.Popen([exe, str(gui_script), "--target", target_path], creationflags=flags)


if __name__ == "__main__":
    main()
