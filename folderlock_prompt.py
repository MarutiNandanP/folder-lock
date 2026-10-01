"""
folderlock_prompt.py - Fast, compact password prompt modal for unlocking folders.

Designed for instant unlock from:
- Windows Explorer right-click context menu ("Lock / Unlock with FolderLock")
- Double-clicking a locked folder
- Command line or shortcut
"""

import os
import sys
import argparse
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from folderlock_core import (
    unlock_folder,
    is_folder_locked,
    verify_vault_password,
    InvalidPasswordError,
    FolderLockError
)
from folderlock_service import FolderLockClient


class QuickUnlockModal:
    def __init__(self, root: tk.Tk, folder_path: str):
        self.root = root
        self.folder_path = os.path.normpath(folder_path)
        self.folder_name = Path(self.folder_path).name

        self.root.title(f"FolderLock - Unlock {self.folder_name}")
        self.root.geometry("480x320")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        # Center on screen
        self.root.eval("tk::PlaceWindow . center")

        # Styling
        self.root.configure(bg="#f8fafc")
        self._build_ui()

    def _build_ui(self):
        container = tk.Frame(self.root, bg="#ffffff", padx=24, pady=20, relief="solid", bd=1)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        # Header
        hdr = tk.Frame(container, bg="#ffffff")
        hdr.pack(fill="x", pady=(0, 10))

        tk.Label(hdr, text="🛡️", font=("Segoe UI", 24), bg="#ffffff").pack(side="left", padx=(0, 10))

        title_box = tk.Frame(hdr, bg="#ffffff")
        title_box.pack(side="left", fill="x", expand=True)

        tk.Label(
            title_box,
            text=f"Unlock '{self.folder_name}'",
            font=("Segoe UI", 13, "bold"),
            bg="#ffffff",
            fg="#0f172a"
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text=self.folder_path,
            font=("Segoe UI", 8),
            bg="#ffffff",
            fg="#64748b"
        ).pack(anchor="w")

        # Notice
        notice_box = tk.Frame(container, bg="#eff6ff", padx=10, pady=6, relief="solid", bd=1)
        notice_box.pack(fill="x", pady=(0, 12))
        tk.Label(
            notice_box,
            text="🔒 This folder is encrypted with military-grade AES-256-GCM.\n"
                 "Please enter the master password you created when locking it.",
            font=("Segoe UI", 8),
            bg="#eff6ff",
            fg="#1e40af",
            justify="left"
        ).pack(anchor="w")

        # Password Entry
        tk.Label(
            container,
            text="Master Password:",
            font=("Segoe UI", 9, "bold"),
            bg="#ffffff",
            fg="#0f172a"
        ).pack(anchor="w", pady=(0, 4))

        self.pwd_var = tk.StringVar()
        self.entry_pwd = tk.Entry(
            container,
            textvariable=self.pwd_var,
            show="•",
            font=("Segoe UI", 12),
            bg="#f8fafc",
            relief="solid",
            bd=1
        )
        self.entry_pwd.pack(fill="x", ipady=5, pady=(0, 6))
        self.entry_pwd.focus_set()
        self.entry_pwd.bind("<Return>", lambda e: self._submit_unlock())

        # Show password toggle
        self.show_var = tk.BooleanVar(value=False)
        chk_show = tk.Checkbutton(
            container,
            text="Show Password",
            variable=self.show_var,
            command=self._toggle_show,
            font=("Segoe UI", 8),
            bg="#ffffff"
        )
        chk_show.pack(anchor="w", pady=(0, 10))

        # Status text
        self.status_lbl = tk.Label(
            container,
            text="",
            font=("Segoe UI", 9, "bold"),
            bg="#ffffff",
            fg="#64748b"
        )
        self.status_lbl.pack(anchor="w", pady=(0, 8))

        # Button Row
        btn_row = tk.Frame(container, bg="#ffffff")
        btn_row.pack(fill="x", side="bottom")

        self.btn_unlock = tk.Button(
            btn_row,
            text="🔓 Unlock & Open Folder",
            font=("Segoe UI", 10, "bold"),
            bg="#10b981",
            fg="white",
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
            command=self._submit_unlock
        )
        self.btn_unlock.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_cancel = tk.Button(
            btn_row,
            text="Cancel",
            font=("Segoe UI", 9),
            bg="#e2e8f0",
            relief="flat",
            padx=12,
            pady=6,
            command=self.root.destroy
        )
        btn_cancel.pack(side="right")

    def _toggle_show(self):
        ch = "" if self.show_var.get() else "•"
        self.entry_pwd.config(show=ch)

    def _submit_unlock(self):
        pwd = self.pwd_var.get()
        if not pwd:
            self.status_lbl.config(text="⚠️ Please enter the password.", fg="#ef4444")
            return

        self.btn_unlock.config(state="disabled", text="Verifying & Decrypting...")
        self.status_lbl.config(text="Verifying credentials...", fg="#2563eb")

        def worker():
            try:
                # Try service first so auto-lock timer starts
                if FolderLockClient.is_service_running():
                    res = FolderLockClient.call("unlock_folder", {
                        "folder_path": self.folder_path,
                        "password": pwd,
                        "open_explorer": True
                    })
                    if not res.get("success"):
                        err_type = res.get("error_type")
                        if err_type == "invalid_password":
                            raise InvalidPasswordError("Incorrect password. Access denied.")
                        raise FolderLockError(res.get("error"))
                else:
                    unlock_folder(self.folder_path, pwd)
                    if sys.platform == "win32":
                        os.startfile(self.folder_path)

                self.root.after(0, self._on_success)
            except InvalidPasswordError:
                self.root.after(0, self._on_invalid_password)
            except Exception as e:
                self.root.after(0, lambda: self._on_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_success(self):
        self.status_lbl.config(text="✅ Unlocked successfully! Opening folder...", fg="#10b981")
        self.root.after(600, self.root.destroy)

    def _on_invalid_password(self):
        self.btn_unlock.config(state="normal", text="🔓 Unlock & Open Folder")
        self.status_lbl.config(text="❌ Incorrect master password. Access denied.", fg="#ef4444")
        self.entry_pwd.focus_set()
        self.entry_pwd.select_range(0, tk.END)

    def _on_error(self, err: str):
        self.btn_unlock.config(state="normal", text="🔓 Unlock & Open Folder")
        self.status_lbl.config(text=f"❌ Error: {err}", fg="#ef4444")


def open_prompt_for_folder(folder_path: str):
    folder_path = os.path.normpath(folder_path)
    if not is_folder_locked(folder_path):
        flags = 0x08000000 if sys.platform == "win32" else 0
        if getattr(sys, "frozen", False):
            base_dir = Path(sys.executable).parent
            gui_exe = base_dir / "FolderLock.exe"
            if gui_exe.exists():
                import subprocess
                subprocess.Popen([str(gui_exe), "--target", folder_path], creationflags=flags)
                return
        else:
            base_dir = Path(__file__).parent
            python_dir = Path(sys.executable).parent
            pythonw = python_dir / "pythonw.exe"
            exe = str(pythonw) if pythonw.exists() else sys.executable
            gui_py = base_dir / "folderlock_gui.py"
            import subprocess
            subprocess.Popen([exe, str(gui_py), "--target", folder_path], creationflags=flags)
            return

    root = tk.Tk()
    app = QuickUnlockModal(root, folder_path)
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
        open_prompt_for_folder(target)
    else:
        print("Usage: python folderlock_prompt.py <folder_path>")

