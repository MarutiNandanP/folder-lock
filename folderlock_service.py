"""
folderlock_service.py - Continuous Background Daemon & Auto-Lock Service for FolderLock.

Features:
- Runs continuously in the background 24/7 as a service/daemon.
- Provides secure local IPC socket on 127.0.0.1 for GUI and CLI.
- Maintains registry of locked & unlocked folders.
- Automatic Inactivity Lock: Automatically re-locks & shreds plaintext files after timeout.
- Workstation Lock Detection: Automatically locks all folders when user locks screen (Win+L).
- Safe Shutdown Guard: Re-locks all open folders if computer shuts down or service stops.
- Ephemeral in-memory key storage during unlocked session for zero-touch auto-relock.
"""

import os
import sys
import time
import json
import socket
import select
import signal
import secrets
import logging
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from folderlock_core import (
    lock_folder,
    unlock_folder,
    is_folder_locked,
    verify_vault_password,
    FolderLockError,
    InvalidPasswordError
)

# AppData configuration directory
APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".config"))) / "FolderLock"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

REGISTRY_FILE = APP_DATA_DIR / "vault_registry.json"
SERVICE_INFO_FILE = APP_DATA_DIR / "service.json"
LOG_FILE = APP_DATA_DIR / "folderlock_service.log"
CONFIG_FILE = APP_DATA_DIR / "config.json"

DEFAULT_PORT = 52187
DEFAULT_AUTO_LOCK_MINUTES = 10

# Set up logging
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s"
)
logger = logging.getLogger("FolderLockService")


def is_workstation_locked() -> bool:
    """
    Checks if Windows workstation is currently locked (e.g. Win+L).
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        h_desk = user32.OpenInputDesktop(0, False, 0x0100)
        if not h_desk:
            return True
        result = user32.SwitchDesktop(h_desk)
        user32.CloseDesktop(h_desk)
        return not bool(result)
    except Exception:
        return False


def load_config() -> Dict[str, Any]:
    """Loads configuration options."""
    default_cfg = {
        "auto_lock_on_screen_lock": True,
        "default_auto_lock_minutes": DEFAULT_AUTO_LOCK_MINUTES,
        "open_explorer_on_unlock": True,
        "notification_on_auto_lock": True
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_cfg.update(saved)
        except Exception as e:
            logger.warning("Error reading config, using defaults: %s", e)
    return default_cfg


def save_config(cfg: Dict[str, Any]) -> None:
    """Saves configuration options."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logger.error("Error writing config: %s", e)


class FolderLockService:
    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.auth_token = secrets.token_hex(24)
        self.running = False
        self.server_socket: Optional[socket.socket] = None

        # Lock for thread-safe access to registry and sessions
        self._lock = threading.Lock()

        # Ephemeral session cache: {folder_path: {"password": pwd, "unlocked_at": ts, "timeout_seconds": sec}}
        self.unlocked_sessions: Dict[str, Dict[str, Any]] = {}

        # Managed registry: {folder_path: {"status": "locked"|"unlocked", "auto_lock_minutes": int, ...}}
        self.registry: Dict[str, Dict[str, Any]] = self._load_registry()

        self.config = load_config()
        self._was_locked_last_check = False

    def _load_registry(self) -> Dict[str, Dict[str, Any]]:
        reg = {}
        if REGISTRY_FILE.exists():
            try:
                with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                    reg = json.load(f)
            except Exception as e:
                logger.error("Failed to load registry: %s", e)
        # Prune folders that no longer exist on disk
        pruned = {k: v for k, v in reg.items() if Path(k).exists()}
        return pruned

    def _save_registry(self) -> None:
        try:
            with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.registry, f, indent=2)
        except Exception as e:
            logger.error("Failed to save registry: %s", e)

    def _notify(self, title: str, message: str) -> None:
        """Sends a desktop notification if available."""
        logger.info("[NOTIFICATION] %s: %s", title, message)
        # On Windows, try PowerShell balloon / toast if needed
        if sys.platform == "win32" and self.config.get("notification_on_auto_lock", True):
            try:
                ps_cmd = f"""
                [reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null
                $notify = new-object system.windows.forms.notifyicon
                $notify.icon = [system.drawing.systemicons]::Information
                $notify.balloontiptitle = '{title}'
                $notify.balloontiptext = '{message}'
                $notify.balloontipicon = 'Info'
                $notify.visible = $true
                $notify.showballoontip(4000)
                Start-Sleep -Seconds 1
                $notify.dispose()
                """
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                    creationflags=0x08000000  # CREATE_NO_WINDOW
                )
            except Exception:
                pass

    def start(self) -> None:
        """Starts the background service loop."""
        # Check if already running
        if FolderLockClient.is_service_running():
            logger.warning("Another instance of FolderLockService is already running. Exiting.")
            print("FolderLockService is already running.")
            return

        self.running = True
        logger.info("Starting FolderLock Background Service...")

        # Setup TCP socket on loopback
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Note: Do NOT set SO_REUSEADDR on Windows to avoid socket hijacking / port conflicts

        try:
            self.server_socket.bind(("127.0.0.1", self.port))
        except OSError:
            # Fallback to an available port
            self.server_socket.bind(("127.0.0.1", 0))
            self.port = self.server_socket.getsockname()[1]

        self.server_socket.listen(10)
        self.server_socket.settimeout(1.0)

        # Write service metadata for clients
        service_info = {
            "pid": os.getpid(),
            "port": self.port,
            "token": self.auth_token,
            "started_at": time.time(),
        }
        with open(SERVICE_INFO_FILE, "w", encoding="utf-8") as f:
            json.dump(service_info, f, indent=2)

        logger.info("FolderLock Service listening on 127.0.0.1:%d (PID %d)", self.port, os.getpid())

        # Start background monitor thread
        monitor_thread = threading.Thread(target=self._monitor_loop, name="ServiceMonitor", daemon=True)
        monitor_thread.start()

        # Handle shutdown signals
        self._setup_signals()

        # Run IPC accept loop
        try:
            while self.running:
                try:
                    client_sock, _ = self.server_socket.accept()
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_sock,),
                        daemon=True
                    )
                    client_thread.start()
                except socket.timeout:
                    continue
                except OSError:
                    break
        finally:
            self.stop()

    def _setup_signals(self) -> None:
        def handle_exit(signum, frame):
            logger.info("Signal %s received. Stopping service safely...", signum)
            self.stop()
            sys.exit(0)

        try:
            signal.signal(signal.SIGINT, handle_exit)
            signal.signal(signal.SIGTERM, handle_exit)
        except Exception:
            pass

    def stop(self) -> None:
        """Stops the service cleanly, re-locking all open vaults."""
        if not self.running:
            return
        logger.info("Stopping FolderLock Service...")
        self.running = False

        # Lock all open vaults on shutdown
        with self._lock:
            for folder_path in list(self.unlocked_sessions.keys()):
                logger.info("Shutdown guard: Locking folder '%s'...", folder_path)
                try:
                    self._do_lock_folder(folder_path)
                except Exception as e:
                    logger.error("Failed to re-lock '%s' on shutdown: %s", folder_path, e)

        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

        # Remove service metadata file
        if SERVICE_INFO_FILE.exists():
            try:
                SERVICE_INFO_FILE.unlink()
            except Exception:
                pass

        logger.info("FolderLock Service stopped.")

    def _monitor_loop(self) -> None:
        """Background thread monitoring timeouts and workstation lock events."""
        while self.running:
            try:
                time.sleep(1.0)
                now = time.time()

                # 1. Check Workstation Lock (Win+L)
                if self.config.get("auto_lock_on_screen_lock", True):
                    locked_now = is_workstation_locked()
                    if locked_now and not self._was_locked_last_check:
                        logger.warning("Workstation lock detected! Auto-locking all open vaults immediately.")
                        self.lock_all_now(reason="Workstation locked")
                    self._was_locked_last_check = locked_now

                # 2. Check Inactivity Auto-Lock Timers
                with self._lock:
                    to_lock = []
                    for folder_path, session in self.unlocked_sessions.items():
                        timeout_sec = session.get("timeout_seconds", 0)
                        if timeout_sec > 0:
                            elapsed = now - session.get("unlocked_at", now)
                            if elapsed >= timeout_sec:
                                to_lock.append(folder_path)

                for folder_path in to_lock:
                    logger.info("Auto-lock timer expired for '%s'. Re-locking...", folder_path)
                    try:
                        self._do_lock_folder(folder_path)
                        folder_name = Path(folder_path).name
                        self._notify(
                            "FolderLock Auto-Lock",
                            f"Folder '{folder_name}' was automatically locked and encrypted."
                        )
                    except Exception as e:
                        logger.error("Auto-lock failed for '%s': %s", folder_path, e)
                        # Clean up session to prevent infinite loop on invalid/missing folders
                        with self._lock:
                            if folder_path in self.unlocked_sessions:
                                del self.unlocked_sessions[folder_path]

            except Exception as e:
                logger.error("Error in monitor loop: %s", e)

    def _do_lock_folder(self, folder_path: str, password: Optional[str] = None) -> Dict[str, Any]:
        """Core internal lock execution under thread-lock."""
        p_str = str(Path(folder_path).resolve())

        if not Path(p_str).exists():
            with self._lock:
                if p_str in self.unlocked_sessions:
                    del self.unlocked_sessions[p_str]
                if p_str in self.registry:
                    del self.registry[p_str]
                    self._save_registry()
            raise FolderLockError(f"Directory does not exist: {p_str}")

        # If password not passed, check active ephemeral session
        if not password:
            session = self.unlocked_sessions.get(p_str)
            if session and "password" in session:
                password = session["password"]

        if not password:
            raise FolderLockError("No password available to lock folder. Please provide password.")

        res = lock_folder(p_str, password)

        # Clear ephemeral session password
        if p_str in self.unlocked_sessions:
            del self.unlocked_sessions[p_str]

        # Update registry
        reg_item = self.registry.get(p_str, {})
        reg_item["status"] = "locked"
        reg_item["last_locked_at"] = time.time()
        self.registry[p_str] = reg_item
        self._save_registry()

        return res

    def lock_all_now(self, reason: str = "Manual") -> int:
        """Locks all currently unlocked folders."""
        locked_count = 0
        with self._lock:
            open_folders = list(self.unlocked_sessions.keys())

        for folder_path in open_folders:
            try:
                self._do_lock_folder(folder_path)
                locked_count += 1
            except Exception as e:
                logger.error("Failed to lock '%s' during lock_all: %s", folder_path, e)

        if locked_count > 0:
            self._notify(
                "FolderLock Security",
                f"All {locked_count} open folder(s) locked ({reason})."
            )
        return locked_count

    def _handle_client(self, sock: socket.socket) -> None:
        """Handles an incoming IPC client connection."""
        try:
            sock.settimeout(10.0)
            data_buf = b""
            while b"\n" not in data_buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data_buf += chunk

            if not data_buf:
                sock.close()
                return

            line, _, _ = data_buf.partition(b"\n")
            req = json.loads(line.decode("utf-8"))

            # Authenticate client
            token = req.get("token")
            if token != self.auth_token:
                response = {"success": False, "error": "Unauthorized: invalid service token"}
                sock.sendall(json.dumps(response).encode("utf-8") + b"\n")
                sock.close()
                return

            action = req.get("action")
            params = req.get("params", {})
            response = self._dispatch_action(action, params)

            sock.sendall(json.dumps(response).encode("utf-8") + b"\n")
        except Exception as e:
            logger.error("IPC client error: %s", e)
            try:
                sock.sendall(json.dumps({"success": False, "error": str(e)}).encode("utf-8") + b"\n")
            except Exception:
                pass
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _dispatch_action(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches an action requested over IPC."""
        try:
            if action == "ping":
                with self._lock:
                    open_count = len(self.unlocked_sessions)
                return {
                    "success": True,
                    "data": {
                        "status": "running",
                        "port": self.port,
                        "pid": os.getpid(),
                        "managed_vaults_count": len(self.registry),
                        "open_vaults_count": open_count
                    }
                }

            elif action == "list_vaults":
                now = time.time()
                with self._lock:
                    result_vaults = []
                    for folder_path, item in self.registry.items():
                        is_locked = is_folder_locked(folder_path)
                        session = self.unlocked_sessions.get(folder_path)
                        remaining_sec = None
                        if session and session.get("timeout_seconds", 0) > 0:
                            elapsed = now - session["unlocked_at"]
                            remaining_sec = max(0, int(session["timeout_seconds"] - elapsed))

                        result_vaults.append({
                            "folder_path": folder_path,
                            "folder_name": Path(folder_path).name,
                            "is_locked": is_locked,
                            "auto_lock_minutes": item.get("auto_lock_minutes", DEFAULT_AUTO_LOCK_MINUTES),
                            "remaining_seconds": remaining_sec,
                            "is_active_session": session is not None
                        })
                return {"success": True, "data": result_vaults}

            elif action == "lock_folder":
                folder_path = params.get("folder_path")
                password = params.get("password")
                auto_lock_min = params.get("auto_lock_minutes", DEFAULT_AUTO_LOCK_MINUTES)
                p_str = str(Path(folder_path).resolve())

                with self._lock:
                    res = self._do_lock_folder(p_str, password)
                    reg_item = self.registry.get(p_str, {})
                    reg_item["auto_lock_minutes"] = auto_lock_min
                    self.registry[p_str] = reg_item
                    self._save_registry()

                return {"success": True, "data": res}

            elif action == "unlock_folder":
                folder_path = params.get("folder_path")
                password = params.get("password")
                auto_lock_min = params.get("auto_lock_minutes", None)
                open_explorer = params.get("open_explorer", True)
                p_str = str(Path(folder_path).resolve())

                # Unlock folder
                res = unlock_folder(p_str, password)

                with self._lock:
                    if auto_lock_min is None:
                        reg_item = self.registry.get(p_str, {})
                        auto_lock_min = reg_item.get("auto_lock_minutes", DEFAULT_AUTO_LOCK_MINUTES)

                    # Store session with password in memory for auto-lock
                    timeout_sec = int(auto_lock_min * 60) if auto_lock_min > 0 else 0
                    self.unlocked_sessions[p_str] = {
                        "password": password,
                        "unlocked_at": time.time(),
                        "timeout_seconds": timeout_sec
                    }

                    reg_item = self.registry.get(p_str, {})
                    reg_item["status"] = "unlocked"
                    reg_item["auto_lock_minutes"] = auto_lock_min
                    reg_item["last_unlocked_at"] = time.time()
                    self.registry[p_str] = reg_item
                    self._save_registry()

                # Open folder in Windows Explorer if requested
                if open_explorer and sys.platform == "win32":
                    try:
                        os.startfile(p_str)
                    except Exception as e:
                        logger.warning("Could not open explorer: %s", e)

                return {"success": True, "data": res}

            elif action == "lock_all":
                count = self.lock_all_now(reason="User command")
                return {"success": True, "data": {"locked_count": count}}

            elif action == "register_folder":
                folder_path = params.get("folder_path")
                auto_lock_min = params.get("auto_lock_minutes", DEFAULT_AUTO_LOCK_MINUTES)
                p_str = str(Path(folder_path).resolve())
                with self._lock:
                    self.registry[p_str] = {
                        "status": "locked" if is_folder_locked(p_str) else "unlocked",
                        "auto_lock_minutes": auto_lock_min
                    }
                    self._save_registry()
                return {"success": True}

            elif action == "unregister_folder":
                folder_path = params.get("folder_path")
                p_str = str(Path(folder_path).resolve())
                with self._lock:
                    if p_str in self.registry:
                        del self.registry[p_str]
                        self._save_registry()
                    if p_str in self.unlocked_sessions:
                        del self.unlocked_sessions[p_str]
                return {"success": True}

            elif action == "set_config":
                new_cfg = params.get("config", {})
                self.config.update(new_cfg)
                save_config(self.config)
                return {"success": True, "data": self.config}

            elif action == "get_config":
                return {"success": True, "data": self.config}

            elif action == "stop_service":
                threading.Thread(target=self.stop, daemon=True).start()
                return {"success": True, "data": "Service stopping"}

            else:
                return {"success": False, "error": f"Unknown action: {action}"}

        except InvalidPasswordError as e:
            return {"success": False, "error": str(e), "error_type": "invalid_password"}
        except FolderLockError as e:
            return {"success": False, "error": str(e), "error_type": "folderlock_error"}
        except Exception as e:
            logger.exception("Unexpected error handling action '%s'", action)
            return {"success": False, "error": f"Internal error: {e}"}


# Client IPC helper
class FolderLockClient:
    """Helper client to communicate with the running FolderLock service."""
    @staticmethod
    def get_service_info() -> Optional[Dict[str, Any]]:
        if not SERVICE_INFO_FILE.exists():
            return None
        try:
            with open(SERVICE_INFO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    @classmethod
    def is_service_running(cls) -> bool:
        info = cls.get_service_info()
        if not info:
            return False
        # Try pinging
        try:
            res = cls.call("ping")
            return res.get("success") is True
        except Exception:
            return False

    @classmethod
    def call(cls, action: str, params: Optional[Dict[str, Any]] = None, timeout: float = 15.0) -> Dict[str, Any]:
        info = cls.get_service_info()
        if not info:
            raise ConnectionError("FolderLock service is not running.")

        port = info["port"]
        token = info["token"]

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect(("127.0.0.1", port))
            req = {"token": token, "action": action, "params": params or {}}
            sock.sendall(json.dumps(req).encode("utf-8") + b"\n")

            data = b""
            while b"\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk

            if not data:
                raise ConnectionError("Empty response from FolderLock service.")

            line, _, _ = data.partition(b"\n")
            return json.loads(line.decode("utf-8"))
        finally:
            sock.close()


def run_service():
    """Entry point to launch the background service."""
    service = FolderLockService()
    service.start()


if __name__ == "__main__":
    run_service()
