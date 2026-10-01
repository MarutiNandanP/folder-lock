"""
folderlock_cli.py - Command Line Interface for FolderLock.

Supports:
- Locking folders with password and auto-relock timeout.
- Unlocking folders with password and launching Explorer.
- Querying vault status and listing all managed vaults.
- Managing the continuous background service.
"""

import sys
import os
import time
import getpass
import argparse
import subprocess
from pathlib import Path
from typing import Optional

from folderlock_core import (
    lock_folder,
    unlock_folder,
    is_folder_locked,
    verify_vault_password,
    FolderLockError,
    InvalidPasswordError
)
from folderlock_service import (
    FolderLockClient,
    run_service,
    SERVICE_INFO_FILE
)


def ensure_service_running() -> bool:
    """Checks if background service is running; if not, attempts to spawn it with pythonw."""
    if FolderLockClient.is_service_running():
        return True

    # Attempt to start service in background
    python_dir = Path(sys.executable).parent
    pythonw = python_dir / "pythonw.exe"
    exec_bin = str(pythonw) if pythonw.exists() else sys.executable
    service_script = Path(__file__).parent / "folderlock_service.py"

    try:
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        subprocess.Popen(
            [exec_bin, str(service_script)],
            creationflags=flags,
            close_fds=True
        )
        # Wait up to 3 seconds for service to bind
        for _ in range(15):
            time.sleep(0.2)
            if FolderLockClient.is_service_running():
                return True
    except Exception as e:
        print(f"[!] Warning: Could not auto-launch background service: {e}")

    return FolderLockClient.is_service_running()


def cli_lock(args):
    folder_path = str(Path(args.path).resolve())
    if not os.path.isdir(folder_path):
        print(f"[-] Error: Directory does not exist: {folder_path}")
        sys.exit(1)

    if is_folder_locked(folder_path):
        print(f"[-] Warning: Folder is already locked: {folder_path}")
        sys.exit(1)

    password = args.password
    if not password:
        password = getpass.getpass("Enter master password to lock folder: ")
        confirm = getpass.getpass("Confirm master password: ")
        if password != confirm:
            print("[-] Error: Passwords do not match.")
            sys.exit(1)

    if not password:
        print("[-] Error: Password cannot be empty.")
        sys.exit(1)

    print(f"[*] Locking and encrypting '{folder_path}' (AES-256-GCM)...")

    # If service is active, register with service
    if ensure_service_running():
        try:
            res = FolderLockClient.call("lock_folder", {
                "folder_path": folder_path,
                "password": password,
                "auto_lock_minutes": args.timeout
            })
            if res.get("success"):
                data = res.get("data", {})
                print(f"[+] Folder successfully locked!")
                print(f"    - Files encrypted: {data.get('file_count', 'N/A')}")
                print(f"    - Auto-lock timeout: {args.timeout} minute(s)")
                print(f"    - Background service is actively guarding this folder.")
                return
            else:
                print(f"[-] Service lock failed: {res.get('error')}")
                sys.exit(1)
        except Exception as e:
            print(f"[!] IPC to service failed ({e}), falling back to direct lock...")

    # Direct fallback lock
    def progress_cb(msg, pct):
        print(f"    [{int(pct*100):3d}%] {msg}")

    try:
        res = lock_folder(folder_path, password, progress_callback=progress_cb)
        print(f"[+] Folder successfully locked!")
        print(f"    - Files encrypted: {res.get('file_count', 'N/A')}")
        print(f"    - Vault size: {res.get('vault_size', 'N/A')} bytes")
    except Exception as e:
        print(f"[-] Error locking folder: {e}")
        sys.exit(1)


def cli_unlock(args):
    folder_path = str(Path(args.path).resolve())
    if not os.path.isdir(folder_path):
        print(f"[-] Error: Directory does not exist: {folder_path}")
        sys.exit(1)

    if not is_folder_locked(folder_path):
        print(f"[-] Info: Folder is not locked: {folder_path}")
        sys.exit(1)

    password = args.password
    if not password:
        password = getpass.getpass(f"Enter password to unlock '{Path(folder_path).name}': ")

    print(f"[*] Unlocking '{folder_path}'...")

    open_explorer = not args.no_open

    # Try through service so it can track auto-relock timer
    if ensure_service_running():
        try:
            res = FolderLockClient.call("unlock_folder", {
                "folder_path": folder_path,
                "password": password,
                "auto_lock_minutes": args.timeout,
                "open_explorer": open_explorer
            })
            if res.get("success"):
                data = res.get("data", {})
                print(f"[+] Folder unlocked successfully!")
                print(f"    - Files restored: {data.get('restored_files', 'N/A')}")
                if args.timeout > 0:
                    print(f"    - Auto-relock timer active: will re-lock in {args.timeout} minute(s).")
                if open_explorer:
                    print(f"    - Opened in Windows File Explorer.")
                return
            else:
                err_type = res.get("error_type")
                if err_type == "invalid_password":
                    print("[-] Error: Incorrect password. Access denied.")
                else:
                    print(f"[-] Error unlocking folder: {res.get('error')}")
                sys.exit(1)
        except Exception as e:
            print(f"[!] IPC to service failed ({e}), falling back to direct unlock...")

    # Direct fallback unlock
    def progress_cb(msg, pct):
        print(f"    [{int(pct*100):3d}%] {msg}")

    try:
        res = unlock_folder(folder_path, password, progress_callback=progress_cb)
        print(f"[+] Folder unlocked successfully!")
        print(f"    - Files restored: {res.get('restored_files', 'N/A')}")
        if open_explorer and sys.platform == "win32":
            os.startfile(folder_path)
    except InvalidPasswordError:
        print("[-] Error: Incorrect password. Access denied.")
        sys.exit(1)
    except Exception as e:
        print(f"[-] Error unlocking folder: {e}")
        sys.exit(1)


def cli_status(args):
    folder_path = str(Path(args.path).resolve())
    if not os.path.exists(folder_path):
        print(f"[-] Path does not exist: {folder_path}")
        sys.exit(1)

    locked = is_folder_locked(folder_path)
    print(f"Folder: {folder_path}")
    print(f"Status: {'LOCKED (Encrypted AES-256)' if locked else 'UNLOCKED (Plaintext)'}")

    if FolderLockClient.is_service_running():
        try:
            res = FolderLockClient.call("list_vaults")
            if res.get("success"):
                for v in res["data"]:
                    if v["folder_path"] == folder_path:
                        print(f"Service Tracked: Yes")
                        print(f"Auto-Lock Setting: {v.get('auto_lock_minutes')} min")
                        if v.get("remaining_seconds") is not None:
                            print(f"Auto-Lock Countdown: {v.get('remaining_seconds')} seconds remaining")
                        break
        except Exception:
            pass


def cli_list(args):
    if not FolderLockClient.is_service_running():
        print("[-] Background service is not running. Start with: python folderlock_cli.py service start")
        sys.exit(1)

    res = FolderLockClient.call("list_vaults")
    if not res.get("success"):
        print(f"[-] Failed to fetch list: {res.get('error')}")
        sys.exit(1)

    vaults = res.get("data", [])
    if not vaults:
        print("[*] No folders registered yet. Lock a folder to add it.")
        return

    print("=" * 80)
    print(f"{'FOLDER NAME':<25} {'STATUS':<15} {'AUTO-LOCK':<12} {'PATH'}")
    print("=" * 80)
    for v in vaults:
        status = "LOCKED" if v["is_locked"] else "UNLOCKED"
        if not v["is_locked"] and v.get("remaining_seconds") is not None:
            status += f" ({v['remaining_seconds']}s)"
        timeout_str = f"{v.get('auto_lock_minutes')} min"
        print(f"{v['folder_name']:<25} {status:<15} {timeout_str:<12} {v['folder_path']}")
    print("=" * 80)


def cli_lock_all(args):
    if not FolderLockClient.is_service_running():
        print("[-] Background service is not running.")
        sys.exit(1)

    res = FolderLockClient.call("lock_all")
    if res.get("success"):
        count = res["data"]["locked_count"]
        print(f"[+] Successfully locked all open folders ({count} folder(s) locked).")
    else:
        print(f"[-] Failed to lock all: {res.get('error')}")


def cli_service(args):
    sub = args.service_action
    if sub == "status":
        if FolderLockClient.is_service_running():
            info = FolderLockClient.get_service_info()
            res = FolderLockClient.call("ping")
            data = res.get("data", {})
            print("[+] FolderLock Background Service is RUNNING.")
            print(f"    - PID: {data.get('pid')}")
            print(f"    - Port: 127.0.0.1:{data.get('port')}")
            print(f"    - Managed Vaults: {data.get('managed_vaults_count')}")
            print(f"    - Currently Open: {data.get('open_vaults_count')}")
        else:
            print("[-] FolderLock Background Service is STOPPED.")

    elif sub == "start":
        if FolderLockClient.is_service_running():
            print("[*] Service is already running.")
            return

        python_dir = Path(sys.executable).parent
        pythonw = python_dir / "pythonw.exe"
        exec_bin = str(pythonw) if pythonw.exists() else sys.executable
        service_script = Path(__file__).parent / "folderlock_service.py"

        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        subprocess.Popen([exec_bin, str(service_script)], creationflags=flags, close_fds=True)

        for _ in range(15):
            time.sleep(0.2)
            if FolderLockClient.is_service_running():
                print("[+] FolderLock Background Service started successfully.")
                return

        print("[-] Failed to start service. Check logs.")

    elif sub == "stop":
        if not FolderLockClient.is_service_running():
            print("[*] Service is not running.")
            return

        try:
            FolderLockClient.call("stop_service")
            print("[+] Service stop signal sent. Open vaults safely locked.")
        except Exception as e:
            print(f"[-] Error stopping service: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="FolderLock - Military-Grade AES-256 Folder Lock & Background Security Service"
    )
    subparsers = parser.add_subparsers(dest="command")

    # Lock command
    p_lock = subparsers.add_parser("lock", help="Lock and encrypt a folder")
    p_lock.add_argument("path", help="Folder path to lock")
    p_lock.add_argument("-p", "--password", help="Master password (prompts if omitted)")
    p_lock.add_argument("-t", "--timeout", type=float, default=10.0, help="Auto-lock inactivity timeout in minutes (default: 10)")
    p_lock.set_defaults(func=cli_lock)

    # Unlock command
    p_unlock = subparsers.add_parser("unlock", help="Unlock and decrypt a folder")
    p_unlock.add_argument("path", help="Folder path to unlock")
    p_unlock.add_argument("-p", "--password", help="Master password (prompts if omitted)")
    p_unlock.add_argument("-t", "--timeout", type=float, default=10.0, help="Auto-lock inactivity timeout in minutes (default: 10)")
    p_unlock.add_argument("--no-open", action="store_true", help="Do not open folder in Explorer upon unlock")
    p_unlock.set_defaults(func=cli_unlock)

    # Status command
    p_status = subparsers.add_parser("status", help="Check lock status of a folder")
    p_status.add_argument("path", help="Folder path to check")
    p_status.set_defaults(func=cli_status)

    # List command
    p_list = subparsers.add_parser("list", help="List all registered vaults and their statuses")
    p_list.set_defaults(func=cli_list)

    # Lock all
    p_lockall = subparsers.add_parser("lock-all", help="Immediately lock all open folders")
    p_lockall.set_defaults(func=cli_lock_all)

    # Service command
    p_svc = subparsers.add_parser("service", help="Manage background service")
    p_svc.add_argument("service_action", choices=["start", "stop", "status"], help="Action: start | stop | status")
    p_svc.set_defaults(func=cli_service)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
