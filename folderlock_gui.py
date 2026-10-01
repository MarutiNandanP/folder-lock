"""
folderlock_gui.py - Modern Desktop Graphical User Interface & System Tray for FolderLock.

Features:
- Lock any folder with military-grade AES-256-GCM encryption.
- Unlock folders and automatically open in Windows Explorer.
- Live dashboard displaying all vaults and real-time auto-lock countdowns.
- Background Service management (Start, Stop, Auto-start with Windows).
- Windows Explorer context menu installer.
- System Tray integration with background persistence.
- Works seamlessly with or without background service running.
"""

import os
import sys
import time
import argparse
import threading
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# PIL & pystray for system tray and icons
try:
    from PIL import Image, ImageDraw
    import pystray
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

from folderlock_core import (
    lock_folder,
    unlock_folder,
    is_folder_locked,
    verify_vault_password,
    FolderLockError,
    InvalidPasswordError,
    FileInUseError,
    VaultCorruptedError
)
from folderlock_service import (
    FolderLockClient,
    APP_DATA_DIR,
    load_config,
    save_config
)
import folderlock_autostart
import folderlock_context_menu


def create_shield_icon_image(size: int = 64, color: str = "#2563eb") -> "Image.Image":
    """Generates an in-memory shield icon for window and system tray."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Draw shield polygon
    pts = [
        (size * 0.5, size * 0.08),
        (size * 0.88, size * 0.22),
        (size * 0.88, size * 0.58),
        (size * 0.5, size * 0.94),
        (size * 0.12, size * 0.58),
        (size * 0.12, size * 0.22),
    ]
    draw.polygon(pts, fill=color)
    # Draw keyhole / lock inside
    draw.ellipse([size * 0.40, size * 0.35, size * 0.60, size * 0.55], fill="white")
    draw.polygon([
        (size * 0.43, size * 0.50),
        (size * 0.57, size * 0.50),
        (size * 0.60, size * 0.72),
        (size * 0.40, size * 0.72),
    ], fill="white")
    return img


def check_password_strength(password: str) -> tuple[int, str, str]:
    """Returns (score 0-4, label, hex_color)."""
    if not password:
        return 0, "None", "#94a3b8"
    score = 0
    if len(password) >= 8:
        score += 1
    if len(password) >= 12:
        score += 1
    if any(c.isupper() for c in password) and any(c.islower() for c in password):
        score += 1
    if any(c.isdigit() for c in password) and any(not c.isalnum() for c in password):
        score += 1

    labels = ["Very Weak", "Weak", "Fair", "Strong", "Very Strong"]
    colors = ["#ef4444", "#f97316", "#eab308", "#10b981", "#059669"]
    return score, labels[score], colors[score]


class FolderLockGUI:
    def __init__(self, root: tk.Tk, target_folder: Optional[str] = None):
        self.root = root
        self.root.title("FolderLock - AES-256 Vault & Security Service")
        self.root.geometry("820x640")
        self.root.minsize(760, 580)

        # Style configuration
        self._setup_styles()

        # Config & State
        self.config = load_config()
        self.tray_icon = None
        self.is_closing = False
        self.active_vaults: List[Dict[str, Any]] = []

        # App Icon
        if TRAY_AVAILABLE:
            try:
                self.icon_img = create_shield_icon_image(64, "#2563eb")
                # Save temp icon for Tkinter
                icon_path = APP_DATA_DIR / "app_icon.ico"
                self.icon_img.save(str(icon_path), format="ICO")
                self.root.iconbitmap(str(icon_path))
            except Exception:
                pass

        # Build Main UI
        self._build_header()
        self._build_tabs()
        self._build_status_bar()

        # Handle target folder from CLI / context menu
        if target_folder:
            self._handle_initial_target(target_folder)

        # Start periodic background UI refresh (1 sec timer)
        self.root.after(500, self._periodic_refresh)

        # Initialize System Tray if available
        if TRAY_AVAILABLE:
            self._setup_tray()

        # Ensure background service is running quietly
        self._ensure_service_running_async()

    def _ensure_service_running_async(self):
        def worker():
            if not FolderLockClient.is_service_running():
                python_dir = Path(sys.executable).parent
                pythonw = python_dir / "pythonw.exe"
                exec_bin = str(pythonw) if pythonw.exists() else sys.executable
                service_script = Path(__file__).parent / "folderlock_service.py"
                flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
                try:
                    subprocess.Popen([exec_bin, str(service_script)], creationflags=flags, close_fds=True)
                except Exception:
                    pass
                for _ in range(15):
                    time.sleep(0.2)
                    if FolderLockClient.is_service_running():
                        break
                self.root.after(0, self._periodic_refresh)

        threading.Thread(target=worker, daemon=True).start()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        # Color constants
        self.BG_MAIN = "#f8fafc"
        self.BG_CARD = "#ffffff"
        self.TEXT_PRIMARY = "#0f172a"
        self.TEXT_MUTED = "#64748b"
        self.PRIMARY_BLUE = "#2563eb"
        self.SUCCESS_GREEN = "#10b981"
        self.DANGER_RED = "#ef4444"
        self.BORDER_COLOR = "#e2e8f0"

        self.root.configure(bg=self.BG_MAIN)

        # TTK styles
        style.configure("TNotebook", background=self.BG_MAIN, borderwidth=0)
        style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=[16, 8])
        style.map("TNotebook.Tab",
                  background=[("selected", "#ffffff"), ("!selected", "#e2e8f0")],
                  foreground=[("selected", self.PRIMARY_BLUE), ("!selected", self.TEXT_MUTED)])

        style.configure("Card.TFrame", background=self.BG_CARD, relief="solid", borderwidth=1)
        style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), background=self.BG_MAIN, foreground=self.TEXT_PRIMARY)
        style.configure("SubHeader.TLabel", font=("Segoe UI", 9), background=self.BG_MAIN, foreground=self.TEXT_MUTED)
        style.configure("Section.TLabel", font=("Segoe UI", 11, "bold"), background=self.BG_CARD, foreground=self.TEXT_PRIMARY)
        style.configure("Body.TLabel", font=("Segoe UI", 10), background=self.BG_CARD, foreground=self.TEXT_PRIMARY)
        style.configure("Muted.TLabel", font=("Segoe UI", 9), background=self.BG_CARD, foreground=self.TEXT_MUTED)

    def _build_header(self):
        hdr_frame = tk.Frame(self.root, bg=self.BG_MAIN, padx=20, pady=12)
        hdr_frame.pack(fill="x")

        # Title & Subtitle
        title_box = tk.Frame(hdr_frame, bg=self.BG_MAIN)
        title_box.pack(side="left")

        title_lbl = tk.Label(
            title_box,
            text="🛡️ FolderLock",
            font=("Segoe UI", 17, "bold"),
            bg=self.BG_MAIN,
            fg=self.PRIMARY_BLUE
        )
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(
            title_box,
            text="AES-256 Authenticated Encryption & Continuous Auto-Lock Daemon",
            font=("Segoe UI", 9),
            bg=self.BG_MAIN,
            fg=self.TEXT_MUTED
        )
        sub_lbl.pack(anchor="w")

        # Service Status Badge on Right
        self.svc_badge_frame = tk.Frame(hdr_frame, bg="#e2e8f0", padx=10, pady=6, relief="flat")
        self.svc_badge_frame.pack(side="right")

        self.svc_badge_dot = tk.Label(self.svc_badge_frame, text="●", font=("Segoe UI", 12), fg="#94a3b8", bg="#e2e8f0")
        self.svc_badge_dot.pack(side="left", padx=(0, 5))

        self.svc_badge_text = tk.Label(self.svc_badge_frame, text="Checking Service...", font=("Segoe UI", 9, "bold"), bg="#e2e8f0", fg=self.TEXT_PRIMARY)
        self.svc_badge_text.pack(side="left")

    def _build_tabs(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # Tab Frames
        self.tab_lock = tk.Frame(self.notebook, bg=self.BG_CARD, padx=24, pady=20)
        self.tab_unlock = tk.Frame(self.notebook, bg=self.BG_CARD, padx=24, pady=20)
        self.tab_vaults = tk.Frame(self.notebook, bg=self.BG_CARD, padx=24, pady=20)
        self.tab_settings = tk.Frame(self.notebook, bg=self.BG_CARD, padx=24, pady=20)

        self.notebook.add(self.tab_lock, text=" 🔒 Lock Folder ")
        self.notebook.add(self.tab_unlock, text=" 🔓 Unlock Folder ")
        self.notebook.add(self.tab_vaults, text=" 📋 Active Vaults ")
        self.notebook.add(self.tab_settings, text=" ⚙️ Settings & Service ")

        self._build_tab_lock()
        self._build_tab_unlock()
        self._build_tab_vaults()
        self._build_tab_settings()

    # ---------------- TAB 1: LOCK FOLDER ----------------
    def _build_tab_lock(self):
        f = self.tab_lock

        # Title
        tk.Label(f, text="Lock and Cryptographically Encrypt a Folder", font=("Segoe UI", 13, "bold"), bg=self.BG_CARD, fg=self.TEXT_PRIMARY).pack(anchor="w")
        tk.Label(f, text="Files are archived, encrypted with AES-256-GCM, and original plaintext is shredded from disk.", font=("Segoe UI", 9), bg=self.BG_CARD, fg=self.TEXT_MUTED).pack(anchor="w", pady=(0, 15))

        # Folder Picker
        tk.Label(f, text="Select Folder to Lock:", font=("Segoe UI", 10, "bold"), bg=self.BG_CARD, fg=self.TEXT_PRIMARY).pack(anchor="w")
        folder_row = tk.Frame(f, bg=self.BG_CARD)
        folder_row.pack(fill="x", pady=(4, 12))

        self.lock_path_var = tk.StringVar()
        entry_path = tk.Entry(folder_row, textvariable=self.lock_path_var, font=("Segoe UI", 10), bg="#f8fafc", relief="solid", bd=1)
        entry_path.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))

        btn_browse = tk.Button(folder_row, text="📁 Browse...", font=("Segoe UI", 9, "bold"), bg="#e2e8f0", fg=self.TEXT_PRIMARY, relief="flat", padx=12, command=self._browse_lock_folder)
        btn_browse.pack(side="right")

        # Password Field
        pwd_grid = tk.Frame(f, bg=self.BG_CARD)
        pwd_grid.pack(fill="x", pady=(0, 8))

        col1 = tk.Frame(pwd_grid, bg=self.BG_CARD)
        col1.pack(side="left", fill="x", expand=True, padx=(0, 10))
        tk.Label(col1, text="Create Master Password:", font=("Segoe UI", 10, "bold"), bg=self.BG_CARD, fg=self.TEXT_PRIMARY).pack(anchor="w")
        self.lock_pwd_var = tk.StringVar()
        self.lock_pwd_var.trace_add("write", self._on_password_change)
        self.entry_lock_pwd = tk.Entry(col1, textvariable=self.lock_pwd_var, show="•", font=("Segoe UI", 11), bg="#f8fafc", relief="solid", bd=1)
        self.entry_lock_pwd.pack(fill="x", ipady=4, pady=(4, 0))

        col2 = tk.Frame(pwd_grid, bg=self.BG_CARD)
        col2.pack(side="right", fill="x", expand=True)
        tk.Label(col2, text="Confirm Password:", font=("Segoe UI", 10, "bold"), bg=self.BG_CARD, fg=self.TEXT_PRIMARY).pack(anchor="w")
        self.lock_confirm_var = tk.StringVar()
        self.entry_lock_confirm = tk.Entry(col2, textvariable=self.lock_confirm_var, show="•", font=("Segoe UI", 11), bg="#f8fafc", relief="solid", bd=1)
        self.entry_lock_confirm.pack(fill="x", ipady=4, pady=(4, 0))

        # Show password toggle & Strength bar
        opts_row = tk.Frame(f, bg=self.BG_CARD)
        opts_row.pack(fill="x", pady=(4, 12))

        self.show_pwd_var = tk.BooleanVar(value=False)
        chk_show = tk.Checkbutton(opts_row, text="Show Passwords", variable=self.show_pwd_var, command=self._toggle_lock_pwd_visibility, bg=self.BG_CARD, font=("Segoe UI", 9))
        chk_show.pack(side="left")

        self.strength_lbl = tk.Label(opts_row, text="Strength: None", font=("Segoe UI", 9, "bold"), bg=self.BG_CARD, fg=self.TEXT_MUTED)
        self.strength_lbl.pack(side="right")

        # Auto-Lock Timeout Setting
        timeout_row = tk.Frame(f, bg=self.BG_CARD)
        timeout_row.pack(fill="x", pady=(0, 15))
        tk.Label(timeout_row, text="Auto-Lock Inactivity Timer:", font=("Segoe UI", 10, "bold"), bg=self.BG_CARD, fg=self.TEXT_PRIMARY).pack(side="left", padx=(0, 10))

        self.lock_timeout_var = tk.StringVar(value="10 minutes")
        cb_timeout = ttk.Combobox(
            timeout_row,
            textvariable=self.lock_timeout_var,
            values=["5 minutes", "10 minutes", "15 minutes", "30 minutes", "1 hour", "Never (Manual lock only)"],
            state="readonly",
            width=22
        )
        cb_timeout.pack(side="left")

        # Inactivity Timer Explanation Banner
        info_box = tk.Frame(f, bg="#eff6ff", padx=12, pady=8, relief="solid", bd=1)
        info_box.pack(fill="x", pady=(8, 12))
        tk.Label(
            info_box,
            text="💡 What is Auto-Lock Inactivity Timer?",
            font=("Segoe UI", 9, "bold"),
            bg="#eff6ff",
            fg=self.PRIMARY_BLUE
        ).pack(anchor="w")
        tk.Label(
            info_box,
            text="When you unlock this folder to view/edit files, if you leave your PC unattended, the background service will automatically re-encrypt the folder and shred the plain files once this timer runs out (or immediately if you press Win + L).",
            font=("Segoe UI", 8),
            bg="#eff6ff",
            fg=self.TEXT_PRIMARY,
            justify="left",
            wraplength=680
        ).pack(anchor="w", pady=(2, 0))

        # Big Lock Button
        self.btn_do_lock = tk.Button(
            f,
            text="🔒 Lock & Encrypt Folder Now",
            font=("Segoe UI", 11, "bold"),
            bg=self.PRIMARY_BLUE,
            fg="white",
            relief="flat",
            pady=8,
            cursor="hand2",
            command=self._start_lock_action
        )
        self.btn_do_lock.pack(fill="x", pady=(10, 10))

        # Progress bar & Status label
        self.lock_progress = ttk.Progressbar(f, mode="determinate")
        self.lock_progress.pack(fill="x", pady=(0, 5))
        self.lock_status_lbl = tk.Label(f, text="Ready to lock.", font=("Segoe UI", 9), bg=self.BG_CARD, fg=self.TEXT_MUTED)
        self.lock_status_lbl.pack(anchor="w")

    def _browse_lock_folder(self):
        d = filedialog.askdirectory(title="Select Folder to Lock")
        if d:
            self.lock_path_var.set(os.path.normpath(d))
            if is_folder_locked(d):
                self.lock_status_lbl.config(text="⚠️ Notice: This folder is already locked. Go to Unlock tab.", fg=self.DANGER_RED)
            else:
                self.lock_status_lbl.config(text="Folder ready to be locked.", fg=self.TEXT_MUTED)

    def _toggle_lock_pwd_visibility(self):
        ch = "" if self.show_pwd_var.get() else "•"
        self.entry_lock_pwd.config(show=ch)
        self.entry_lock_confirm.config(show=ch)

    def _on_password_change(self, *args):
        pwd = self.lock_pwd_var.get()
        score, label, color = check_password_strength(pwd)
        self.strength_lbl.config(text=f"Strength: {label}", fg=color)

    def _start_lock_action(self):
        folder_path = self.lock_path_var.get().strip()
        pwd = self.lock_pwd_var.get()
        confirm = self.lock_confirm_var.get()

        if not folder_path or not os.path.isdir(folder_path):
            messagebox.showerror("Error", "Please select a valid existing folder to lock.")
            return

        if is_folder_locked(folder_path):
            messagebox.showwarning("Warning", "This folder is already locked!")
            return

        if not pwd:
            messagebox.showerror("Error", "Please enter a master password.")
            return

        if pwd != confirm:
            messagebox.showerror("Error", "Passwords do not match!")
            return

        # Parse timeout minutes
        t_str = self.lock_timeout_var.get()
        timeout_min = 10
        if "5 min" in t_str:
            timeout_min = 5
        elif "10 min" in t_str:
            timeout_min = 10
        elif "15 min" in t_str:
            timeout_min = 15
        elif "30 min" in t_str:
            timeout_min = 30
        elif "1 hour" in t_str:
            timeout_min = 60
        elif "Never" in t_str:
            timeout_min = 0

        self.btn_do_lock.config(state="disabled")
        self.lock_progress["value"] = 5

        # Run lock in background thread so GUI doesn't freeze
        def worker():
            def cb(msg, pct):
                self.root.after(0, lambda: self._update_lock_progress(msg, pct))

            try:
                if FolderLockClient.is_service_running():
                    cb("Encrypting and registering with background service...", 0.3)
                    res = FolderLockClient.call("lock_folder", {
                        "folder_path": folder_path,
                        "password": pwd,
                        "auto_lock_minutes": timeout_min
                    })
                    if not res.get("success"):
                        raise FolderLockError(res.get("error"))
                else:
                    lock_folder(folder_path, pwd, progress_callback=cb)

                self.root.after(0, lambda: self._on_lock_success(folder_path))
            except Exception as e:
                self.root.after(0, lambda: self._on_lock_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _update_lock_progress(self, msg: str, pct: float):
        self.lock_progress["value"] = int(pct * 100)
        self.lock_status_lbl.config(text=msg, fg=self.TEXT_PRIMARY)

    def _on_lock_success(self, folder_path: str):
        self.lock_progress["value"] = 100
        self.lock_status_lbl.config(text="✅ Folder successfully locked and encrypted!", fg=self.SUCCESS_GREEN)
        self.btn_do_lock.config(state="normal")
        self.lock_pwd_var.set("")
        self.lock_confirm_var.set("")
        messagebox.showinfo(
            "Folder Locked",
            f"Folder '{Path(folder_path).name}' has been securely encrypted with AES-256!\n\n"
            "Original files have been shredded from disk.\n"
            "Unauthorized users cannot view files even if they take the hard drive."
        )
        self._refresh_vaults_list()

    def _on_lock_error(self, err: str):
        self.lock_progress["value"] = 0
        self.lock_status_lbl.config(text=f"❌ Error: {err}", fg=self.DANGER_RED)
        self.btn_do_lock.config(state="normal")
        messagebox.showerror("Lock Failed", f"Failed to lock folder:\n{err}")

    # ---------------- TAB 2: UNLOCK FOLDER ----------------
    def _build_tab_unlock(self):
        f = self.tab_unlock

        # Title
        tk.Label(f, text="Unlock and Decrypt a Locked Folder", font=("Segoe UI", 13, "bold"), bg=self.BG_CARD, fg=self.TEXT_PRIMARY).pack(anchor="w")
        tk.Label(f, text="Enter master password to restore files and open in Windows File Explorer.", font=("Segoe UI", 9), bg=self.BG_CARD, fg=self.TEXT_MUTED).pack(anchor="w", pady=(0, 15))

        # Folder Picker
        tk.Label(f, text="Select Locked Folder:", font=("Segoe UI", 10, "bold"), bg=self.BG_CARD, fg=self.TEXT_PRIMARY).pack(anchor="w")
        folder_row = tk.Frame(f, bg=self.BG_CARD)
        folder_row.pack(fill="x", pady=(4, 12))

        self.unlock_path_var = tk.StringVar()
        entry_path = tk.Entry(folder_row, textvariable=self.unlock_path_var, font=("Segoe UI", 10), bg="#f8fafc", relief="solid", bd=1)
        entry_path.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))

        btn_browse = tk.Button(folder_row, text="📁 Browse...", font=("Segoe UI", 9, "bold"), bg="#e2e8f0", fg=self.TEXT_PRIMARY, relief="flat", padx=12, command=self._browse_unlock_folder)
        btn_browse.pack(side="right")

        # Password Field
        tk.Label(f, text="Enter Master Password:", font=("Segoe UI", 10, "bold"), bg=self.BG_CARD, fg=self.TEXT_PRIMARY).pack(anchor="w")
        pwd_row = tk.Frame(f, bg=self.BG_CARD)
        pwd_row.pack(fill="x", pady=(4, 10))

        self.unlock_pwd_var = tk.StringVar()
        self.entry_unlock_pwd = tk.Entry(pwd_row, textvariable=self.unlock_pwd_var, show="•", font=("Segoe UI", 11), bg="#f8fafc", relief="solid", bd=1)
        self.entry_unlock_pwd.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))

        self.unlock_show_var = tk.BooleanVar(value=False)
        chk_show = tk.Checkbutton(pwd_row, text="Show", variable=self.unlock_show_var, command=self._toggle_unlock_pwd_visibility, bg=self.BG_CARD, font=("Segoe UI", 9))
        chk_show.pack(side="right")

        # Checkbox: Open explorer upon unlock
        self.open_explorer_var = tk.BooleanVar(value=True)
        chk_exp = tk.Checkbutton(f, text="Automatically open folder in Windows Explorer upon unlock", variable=self.open_explorer_var, bg=self.BG_CARD, font=("Segoe UI", 9))
        chk_exp.pack(anchor="w", pady=(0, 15))

        # Big Unlock Button
        self.btn_do_unlock = tk.Button(
            f,
            text="🔓 Unlock & Open Folder",
            font=("Segoe UI", 11, "bold"),
            bg=self.SUCCESS_GREEN,
            fg="white",
            relief="flat",
            pady=8,
            cursor="hand2",
            command=self._start_unlock_action
        )
        self.btn_do_unlock.pack(fill="x", pady=(5, 10))

        # Progress bar & Status label
        self.unlock_progress = ttk.Progressbar(f, mode="determinate")
        self.unlock_progress.pack(fill="x", pady=(0, 5))
        self.unlock_status_lbl = tk.Label(f, text="Ready to unlock.", font=("Segoe UI", 9), bg=self.BG_CARD, fg=self.TEXT_MUTED)
        self.unlock_status_lbl.pack(anchor="w")

    def _browse_unlock_folder(self):
        d = filedialog.askdirectory(title="Select Locked Folder")
        if d:
            self.unlock_path_var.set(os.path.normpath(d))
            if not is_folder_locked(d):
                self.unlock_status_lbl.config(text="⚠️ Notice: This folder does not appear to be locked.", fg=self.DANGER_RED)
            else:
                self.unlock_status_lbl.config(text="Locked vault detected. Enter password to unlock.", fg=self.SUCCESS_GREEN)
            self.entry_unlock_pwd.focus_set()

    def _toggle_unlock_pwd_visibility(self):
        ch = "" if self.unlock_show_var.get() else "•"
        self.entry_unlock_pwd.config(show=ch)

    def _start_unlock_action(self):
        folder_path = self.unlock_path_var.get().strip()
        pwd = self.unlock_pwd_var.get()

        if not folder_path or not os.path.isdir(folder_path):
            messagebox.showerror("Error", "Please select a valid folder.")
            return

        if not is_folder_locked(folder_path):
            messagebox.showinfo("Info", "This folder is not locked.")
            return

        if not pwd:
            messagebox.showerror("Error", "Please enter the password.")
            return

        self.btn_do_unlock.config(state="disabled")
        self.unlock_progress["value"] = 10
        open_exp = self.open_explorer_var.get()

        def worker():
            def cb(msg, pct):
                self.root.after(0, lambda: self._update_unlock_progress(msg, pct))

            try:
                if FolderLockClient.is_service_running():
                    cb("Verifying and unlocking via background service...", 0.4)
                    res = FolderLockClient.call("unlock_folder", {
                        "folder_path": folder_path,
                        "password": pwd,
                        "open_explorer": open_exp
                    })
                    if not res.get("success"):
                        err_type = res.get("error_type")
                        if err_type == "invalid_password":
                            raise InvalidPasswordError("Incorrect password. Access denied.")
                        raise FolderLockError(res.get("error"))
                else:
                    unlock_folder(folder_path, pwd, progress_callback=cb)
                    if open_exp and sys.platform == "win32":
                        os.startfile(folder_path)

                self.root.after(0, lambda: self._on_unlock_success(folder_path))
            except InvalidPasswordError:
                self.root.after(0, lambda: self._on_unlock_invalid_password())
            except Exception as e:
                self.root.after(0, lambda: self._on_unlock_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _update_unlock_progress(self, msg: str, pct: float):
        self.unlock_progress["value"] = int(pct * 100)
        self.unlock_status_lbl.config(text=msg, fg=self.TEXT_PRIMARY)

    def _on_unlock_success(self, folder_path: str):
        self.unlock_progress["value"] = 100
        self.unlock_status_lbl.config(text="✅ Folder unlocked successfully!", fg=self.SUCCESS_GREEN)
        self.btn_do_unlock.config(state="normal")
        self.unlock_pwd_var.set("")
        self._refresh_vaults_list()

    def _on_unlock_invalid_password(self):
        self.unlock_progress["value"] = 0
        self.unlock_status_lbl.config(text="❌ Incorrect password. Access denied.", fg=self.DANGER_RED)
        self.btn_do_unlock.config(state="normal")
        messagebox.showerror("Access Denied", "Incorrect master password. Please verify and try again.")
        self.entry_unlock_pwd.focus_set()

    def _on_unlock_error(self, err: str):
        self.unlock_progress["value"] = 0
        self.unlock_status_lbl.config(text=f"❌ Error: {err}", fg=self.DANGER_RED)
        self.btn_do_unlock.config(state="normal")
        messagebox.showerror("Unlock Failed", f"Could not unlock folder:\n{err}")

    # ---------------- TAB 3: ACTIVE VAULTS DASHBOARD ----------------
    def _build_tab_vaults(self):
        f = self.tab_vaults

        top_row = tk.Frame(f, bg=self.BG_CARD)
        top_row.pack(fill="x", pady=(0, 10))

        tk.Label(top_row, text="Managed Folders & Live Auto-Lock Timers", font=("Segoe UI", 12, "bold"), bg=self.BG_CARD, fg=self.TEXT_PRIMARY).pack(side="left")

        btn_lockall = tk.Button(
            top_row,
            text="⚠️ Lock All Unlocked Now",
            font=("Segoe UI", 9, "bold"),
            bg=self.DANGER_RED,
            fg="white",
            relief="flat",
            padx=10,
            pady=4,
            command=self._lock_all_action
        )
        btn_lockall.pack(side="right")

        btn_refresh = tk.Button(
            top_row,
            text="🔄 Refresh",
            font=("Segoe UI", 9),
            bg="#e2e8f0",
            relief="flat",
            padx=8,
            pady=4,
            command=self._refresh_vaults_list
        )
        btn_refresh.pack(side="right", padx=6)

        # Treeview
        tree_frame = tk.Frame(f, bg=self.BG_CARD)
        tree_frame.pack(fill="both", expand=True)

        columns = ("name", "status", "autolock", "path")
        self.vault_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=10)
        self.vault_tree.heading("name", text="Folder Name")
        self.vault_tree.heading("status", text="Security Status")
        self.vault_tree.heading("autolock", text="Auto-Lock Countdown")
        self.vault_tree.heading("path", text="Path")

        self.vault_tree.column("name", width=160, anchor="w")
        self.vault_tree.column("status", width=140, anchor="center")
        self.vault_tree.column("autolock", width=160, anchor="center")
        self.vault_tree.column("path", width=300, anchor="w")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.vault_tree.yview)
        self.vault_tree.configure(yscrollcommand=scrollbar.set)

        self.vault_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Action bar under table
        actions_bar = tk.Frame(f, bg=self.BG_CARD)
        actions_bar.pack(fill="x", pady=(12, 0))

        btn_lock_sel = tk.Button(actions_bar, text="🔒 Lock Selected", font=("Segoe UI", 9, "bold"), bg=self.PRIMARY_BLUE, fg="white", relief="flat", padx=10, pady=4, command=self._lock_selected_vault)
        btn_lock_sel.pack(side="left", padx=(0, 6))

        btn_unlock_sel = tk.Button(actions_bar, text="🔓 Unlock Selected...", font=("Segoe UI", 9, "bold"), bg=self.SUCCESS_GREEN, fg="white", relief="flat", padx=10, pady=4, command=self._unlock_selected_vault)
        btn_unlock_sel.pack(side="left", padx=(0, 6))

        btn_open_exp = tk.Button(actions_bar, text="📂 Open in Explorer", font=("Segoe UI", 9), bg="#e2e8f0", relief="flat", padx=10, pady=4, command=self._open_selected_in_explorer)
        btn_open_exp.pack(side="left", padx=(0, 6))

        btn_remove = tk.Button(actions_bar, text="Remove from List", font=("Segoe UI", 9), bg="#e2e8f0", relief="flat", padx=10, pady=4, command=self._remove_selected_from_list)
        btn_remove.pack(side="right")

    def _refresh_vaults_list(self):
        """Fetches vaults from service or local config and refreshes Treeview."""
        for item in self.vault_tree.get_children():
            self.vault_tree.delete(item)

        if FolderLockClient.is_service_running():
            try:
                res = FolderLockClient.call("list_vaults")
                if res.get("success"):
                    self.active_vaults = res.get("data", [])
            except Exception:
                pass

        for v in self.active_vaults:
            p = v["folder_path"]
            name = v["folder_name"]
            is_locked = v["is_locked"]

            if is_locked:
                status_text = "🔒 LOCKED (AES-256)"
                countdown_text = "Guarded"
            else:
                status_text = "🔓 UNLOCKED (Open)"
                rem = v.get("remaining_seconds")
                if rem is not None and rem > 0:
                    mins = rem // 60
                    secs = rem % 60
                    countdown_text = f"Auto-lock in {mins:02d}:{secs:02d}"
                elif rem == 0:
                    countdown_text = "Locking now..."
                else:
                    countdown_text = "Manual"

            self.vault_tree.insert("", "end", iid=p, values=(name, status_text, countdown_text, p))

    def _lock_all_action(self):
        if not FolderLockClient.is_service_running():
            messagebox.showwarning("Notice", "Background service is not running.")
            return

        res = FolderLockClient.call("lock_all")
        if res.get("success"):
            count = res["data"]["locked_count"]
            messagebox.showinfo("Lock All", f"Successfully locked {count} folder(s).")
            self._refresh_vaults_list()
        else:
            messagebox.showerror("Error", f"Failed to lock all: {res.get('error')}")

    def _get_selected_vault_path(self) -> Optional[str]:
        selected = self.vault_tree.selection()
        if not selected:
            messagebox.showwarning("Notice", "Please select a folder from the list.")
            return None
        return selected[0]

    def _lock_selected_vault(self):
        p = self._get_selected_vault_path()
        if not p:
            return
        if is_folder_locked(p):
            messagebox.showinfo("Notice", "This folder is already locked.")
            return
        # Switch to lock tab with prefilled path
        self.lock_path_var.set(p)
        self.notebook.select(self.tab_lock)
        self.entry_lock_pwd.focus_set()

    def _unlock_selected_vault(self):
        p = self._get_selected_vault_path()
        if not p:
            return
        if not is_folder_locked(p):
            messagebox.showinfo("Notice", "This folder is already unlocked.")
            return
        self.unlock_path_var.set(p)
        self.notebook.select(self.tab_unlock)
        self.entry_unlock_pwd.focus_set()

    def _open_selected_in_explorer(self):
        p = self._get_selected_vault_path()
        if p and os.path.exists(p) and sys.platform == "win32":
            os.startfile(p)

    def _remove_selected_from_list(self):
        p = self._get_selected_vault_path()
        if not p:
            return
        if FolderLockClient.is_service_running():
            FolderLockClient.call("unregister_folder", {"folder_path": p})
        self._refresh_vaults_list()

    # ---------------- TAB 4: SETTINGS & SERVICE ----------------
    def _build_tab_settings(self):
        f = self.tab_settings

        # Background Service Card
        svc_card = tk.LabelFrame(f, text=" Continuous Background Service ", font=("Segoe UI", 10, "bold"), bg=self.BG_CARD, padx=16, pady=12)
        svc_card.pack(fill="x", pady=(0, 15))

        self.svc_card_status = tk.Label(svc_card, text="Checking background service status...", font=("Segoe UI", 10), bg=self.BG_CARD)
        self.svc_card_status.pack(anchor="w", pady=(0, 8))

        btn_row = tk.Frame(svc_card, bg=self.BG_CARD)
        btn_row.pack(fill="x")

        self.btn_start_svc = tk.Button(btn_row, text="▶ Start Service", font=("Segoe UI", 9, "bold"), bg=self.SUCCESS_GREEN, fg="white", relief="flat", padx=10, pady=4, command=self._start_service_clicked)
        self.btn_start_svc.pack(side="left", padx=(0, 8))

        self.btn_stop_svc = tk.Button(btn_row, text="⏹ Stop Service", font=("Segoe UI", 9), bg="#e2e8f0", relief="flat", padx=10, pady=4, command=self._stop_service_clicked)
        self.btn_stop_svc.pack(side="left")

        # Security Rules
        sec_card = tk.LabelFrame(f, text=" Security & Auto-Lock Automations ", font=("Segoe UI", 10, "bold"), bg=self.BG_CARD, padx=16, pady=12)
        sec_card.pack(fill="x", pady=(0, 15))

        self.cfg_winlock_var = tk.BooleanVar(value=self.config.get("auto_lock_on_screen_lock", True))
        chk_winlock = tk.Checkbutton(
            sec_card,
            text="Automatically lock all folders when Windows workstation is locked (Win + L)",
            variable=self.cfg_winlock_var,
            command=self._save_security_config,
            font=("Segoe UI", 9),
            bg=self.BG_CARD
        )
        chk_winlock.pack(anchor="w", pady=(0, 6))

        self.cfg_notify_var = tk.BooleanVar(value=self.config.get("notification_on_auto_lock", True))
        chk_notify = tk.Checkbutton(
            sec_card,
            text="Show desktop notification when a folder is automatically locked",
            variable=self.cfg_notify_var,
            command=self._save_security_config,
            font=("Segoe UI", 9),
            bg=self.BG_CARD
        )
        chk_notify.pack(anchor="w")

        # Windows System Integration
        sys_card = tk.LabelFrame(f, text=" Windows OS Integration ", font=("Segoe UI", 10, "bold"), bg=self.BG_CARD, padx=16, pady=12)
        sys_card.pack(fill="x")

        # Autostart row
        auto_row = tk.Frame(sys_card, bg=self.BG_CARD)
        auto_row.pack(fill="x", pady=(0, 8))
        self.startup_var = tk.BooleanVar(value=folderlock_autostart.is_startup_enabled())
        chk_startup = tk.Checkbutton(
            auto_row,
            text="Run FolderLock Service automatically on Windows startup",
            variable=self.startup_var,
            command=self._toggle_startup,
            font=("Segoe UI", 9),
            bg=self.BG_CARD
        )
        chk_startup.pack(side="left")

        # Explorer Context Menu
        ctx_row = tk.Frame(sys_card, bg=self.BG_CARD)
        ctx_row.pack(fill="x", pady=(4, 0))
        self.ctx_lbl = tk.Label(ctx_row, text="Windows Explorer Right-Click Menu:", font=("Segoe UI", 9), bg=self.BG_CARD)
        self.ctx_lbl.pack(side="left", padx=(0, 10))

        self.btn_toggle_ctx = tk.Button(
            ctx_row,
            text="Install Context Menu" if not folderlock_context_menu.is_context_menu_installed() else "Uninstall Context Menu",
            font=("Segoe UI", 9),
            bg="#e2e8f0",
            relief="flat",
            padx=10,
            command=self._toggle_context_menu
        )
        self.btn_toggle_ctx.pack(side="left")

        # Windows Service Control Manager (services.msc) Card
        win_svc_card = tk.LabelFrame(f, text=" Windows Service Control Manager (services.msc) ", font=("Segoe UI", 10, "bold"), bg=self.BG_CARD, padx=16, pady=12)
        win_svc_card.pack(fill="x", pady=(15, 0))

        self.win_svc_status_lbl = tk.Label(
            win_svc_card,
            text="Checking services.msc registration...",
            font=("Segoe UI", 9),
            bg=self.BG_CARD,
            fg=self.TEXT_MUTED
        )
        self.win_svc_status_lbl.pack(anchor="w", pady=(0, 6))

        win_btn_row = tk.Frame(win_svc_card, bg=self.BG_CARD)
        win_btn_row.pack(fill="x")

        self.btn_install_win_svc = tk.Button(
            win_btn_row,
            text="Install into services.msc",
            font=("Segoe UI", 9, "bold"),
            bg=self.PRIMARY_BLUE,
            fg="white",
            relief="flat",
            padx=10,
            pady=4,
            command=self._install_windows_service_clicked
        )
        self.btn_install_win_svc.pack(side="left", padx=(0, 8))

        btn_open_msc = tk.Button(
            win_btn_row,
            text="🔍 Open services.msc",
            font=("Segoe UI", 9),
            bg="#e2e8f0",
            relief="flat",
            padx=10,
            pady=4,
            command=self._open_services_msc_clicked
        )
        btn_open_msc.pack(side="left", padx=(0, 8))

        self.btn_uninstall_win_svc = tk.Button(
            win_btn_row,
            text="Uninstall from services.msc",
            font=("Segoe UI", 9),
            bg="#e2e8f0",
            relief="flat",
            padx=10,
            pady=4,
            command=self._uninstall_windows_service_clicked
        )
        self.btn_uninstall_win_svc.pack(side="left")

    def _install_windows_service_clicked(self):
        script = Path(__file__).parent / "install_windows_service.bat"
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.shell32.ShellExecuteW(None, "runas", str(script), "", None, 1)

    def _open_services_msc_clicked(self):
        if sys.platform == "win32":
            subprocess.Popen(["services.msc"], shell=True)

    def _uninstall_windows_service_clicked(self):
        script = Path(__file__).parent / "uninstall_windows_service.bat"
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.shell32.ShellExecuteW(None, "runas", str(script), "", None, 1)

    def _save_security_config(self):
        self.config["auto_lock_on_screen_lock"] = self.cfg_winlock_var.get()
        self.config["notification_on_auto_lock"] = self.cfg_notify_var.get()
        save_config(self.config)
        if FolderLockClient.is_service_running():
            try:
                FolderLockClient.call("set_config", {"config": self.config})
            except Exception:
                pass

    def _toggle_startup(self):
        if self.startup_var.get():
            folderlock_autostart.enable_startup()
        else:
            folderlock_autostart.disable_startup()

    def _toggle_context_menu(self):
        if folderlock_context_menu.is_context_menu_installed():
            folderlock_context_menu.uninstall_context_menu()
            self.btn_toggle_ctx.config(text="Install Context Menu")
        else:
            folderlock_context_menu.install_context_menu()
            self.btn_toggle_ctx.config(text="Uninstall Context Menu")

    def _start_service_clicked(self):
        python_dir = Path(sys.executable).parent
        pythonw = python_dir / "pythonw.exe"
        exec_bin = str(pythonw) if pythonw.exists() else sys.executable
        service_script = Path(__file__).parent / "folderlock_service.py"

        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        subprocess.Popen([exec_bin, str(service_script)], creationflags=flags, close_fds=True)

        for _ in range(15):
            time.sleep(0.2)
            if FolderLockClient.is_service_running():
                break
        self._periodic_refresh()

    def _stop_service_clicked(self):
        if FolderLockClient.is_service_running():
            try:
                FolderLockClient.call("stop_service")
            except Exception:
                pass
        self.root.after(500, self._periodic_refresh)

    # ---------------- STATUS BAR & PERIODIC REFRESH ----------------
    def _build_status_bar(self):
        self.status_bar = tk.Frame(self.root, bg="#e2e8f0", padx=15, pady=4)
        self.status_bar.pack(fill="x", side="bottom")

        self.status_lbl = tk.Label(self.status_bar, text="Ready", font=("Segoe UI", 9), bg="#e2e8f0", fg=self.TEXT_MUTED)
        self.status_lbl.pack(side="left")

        self.ver_lbl = tk.Label(self.status_bar, text="FolderLock v1.0 • AES-256-GCM", font=("Segoe UI", 8), bg="#e2e8f0", fg=self.TEXT_MUTED)
        self.ver_lbl.pack(side="right")

    def _periodic_refresh(self):
        """Called every 1 second to update service status and countdown timers."""
        is_running = FolderLockClient.is_service_running()
        if is_running:
            self.svc_badge_dot.config(text="●", fg=self.SUCCESS_GREEN)
            self.svc_badge_text.config(text="Service Active (24/7 Guard)")
            self.svc_card_status.config(
                text="✅ Background service is RUNNING. Guarding folders in the background.",
                fg=self.SUCCESS_GREEN
            )
            self.btn_start_svc.config(state="disabled")
            self.btn_stop_svc.config(state="normal")
        else:
            self.svc_badge_dot.config(text="●", fg="#f59e0b")
            self.svc_badge_text.config(text="Service Offline")
            self.svc_card_status.config(
                text="⚠️ Background service is STOPPED. Auto-lock timers are inactive.",
                fg="#b45309"
            )
            self.btn_start_svc.config(state="normal")
            self.btn_stop_svc.config(state="disabled")

        # Refresh vaults table live
        self._refresh_vaults_list()

        # Update services.msc status
        try:
            from folderlock_win_service import is_windows_service_installed, get_windows_service_status
            win_inst = is_windows_service_installed()
            win_st = get_windows_service_status()
            if win_inst:
                self.win_svc_status_lbl.config(
                    text=f"✅ Service 'FolderLock' is registered in services.msc (Status: {win_st})",
                    fg=self.SUCCESS_GREEN if win_st == "Running" else "#f59e0b"
                )
                self.btn_install_win_svc.config(state="disabled")
                self.btn_uninstall_win_svc.config(state="normal")
            else:
                self.win_svc_status_lbl.config(
                    text="ℹ️ Service 'FolderLock' is not yet registered in services.msc (Click 'Install' below)",
                    fg=self.TEXT_MUTED
                )
                self.btn_install_win_svc.config(state="normal")
                self.btn_uninstall_win_svc.config(state="disabled")
        except Exception:
            pass

        # Reschedule next tick
        if not self.is_closing:
            self.root.after(1000, self._periodic_refresh)

    def _handle_initial_target(self, target_folder: str):
        target = os.path.normpath(target_folder)
        if is_folder_locked(target):
            self.unlock_path_var.set(target)
            self.notebook.select(self.tab_unlock)
            self.entry_unlock_pwd.focus_set()
        else:
            self.lock_path_var.set(target)
            self.notebook.select(self.tab_lock)
            self.entry_lock_pwd.focus_set()

    # ---------------- SYSTEM TRAY INTEGRATION ----------------
    def _setup_tray(self):
        if not TRAY_AVAILABLE:
            return

        def on_open(icon, item):
            self.root.after(0, self._restore_from_tray)

        def on_lock_all(icon, item):
            self.root.after(0, self._lock_all_action)

        def on_exit(icon, item):
            self.root.after(0, self._full_exit)

        menu = pystray.Menu(
            pystray.MenuItem("🛡️ Open FolderLock", on_open, default=True),
            pystray.MenuItem("🔒 Lock All Folders", on_lock_all),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit FolderLock", on_exit)
        )

        self.tray_icon = pystray.Icon("FolderLock", self.icon_img, "FolderLock AES-256", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _on_close_clicked(self):
        """Minimize to tray instead of quitting if tray is available."""
        if TRAY_AVAILABLE and self.tray_icon:
            self.root.withdraw()
            # Show notification on first minimize
            try:
                self.tray_icon.notify("FolderLock minimized to tray. Still actively guarding folders in the background.", "FolderLock Guard")
            except Exception:
                pass
        else:
            self._full_exit()

    def _restore_from_tray(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _full_exit(self):
        self.is_closing = True
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="FolderLock GUI")
    parser.add_argument("--target", help="Pre-select target folder for lock/unlock", default=None)
    args = parser.parse_args()

    root = tk.Tk()
    app = FolderLockGUI(root, target_folder=args.target)
    root.mainloop()


if __name__ == "__main__":
    main()
