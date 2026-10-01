"""
folderlock_win_service.py - Native Windows SCM Service for FolderLock.

Registers FolderLock in Windows Service Control Manager (services.msc).

Commands:
  python folderlock_win_service.py install
  python folderlock_win_service.py start
  python folderlock_win_service.py stop
  python folderlock_win_service.py restart
  python folderlock_win_service.py remove
"""

import sys
import os
import threading
from pathlib import Path

# Add script directory to sys.path so modules can be imported by SCM in Session 0
BASE_DIR = str(Path(__file__).parent.resolve())
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False


if PYWIN32_AVAILABLE:
    class FolderLockWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_ = "FolderLock"
        _svc_display_name_ = "FolderLock Security & Auto-Lock Service"
        _svc_description_ = "Continuous 24/7 AES-256 folder lock, inactivity auto-lock, and screen lock security service."

        def __init__(self, args):
            super().__init__(args)
            self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
            self.service_instance = None
            self.service_thread = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.hWaitStop)
            if self.service_instance:
                try:
                    self.service_instance.stop()
                except Exception:
                    pass

        def SvcDoRun(self):
            try:
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_INFORMATION_TYPE,
                    servicemanager.PYS_SERVICE_STARTED,
                    (self._svc_name_, "")
                )
            except Exception:
                pass

            from folderlock_service import FolderLockService
            self.service_instance = FolderLockService()
            self.service_thread = threading.Thread(target=self.service_instance.start, daemon=True)
            self.service_thread.start()

            # Wait until SCM signals stop
            win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)

            try:
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_INFORMATION_TYPE,
                    servicemanager.PYS_SERVICE_STOPPED,
                    (self._svc_name_, "")
                )
            except Exception:
                pass


def is_windows_service_installed() -> bool:
    """Checks if 'FolderLock' is registered in Windows Service Control Manager (services.msc)."""
    if sys.platform != "win32" or not PYWIN32_AVAILABLE:
        return False
    try:
        schSCManager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        try:
            hService = win32service.OpenService(schSCManager, "FolderLock", win32service.SERVICE_QUERY_STATUS)
            win32service.CloseServiceHandle(hService)
            return True
        except Exception:
            return False
        finally:
            win32service.CloseServiceHandle(schSCManager)
    except Exception:
        return False


def get_windows_service_status() -> str:
    """Returns 'Running', 'Stopped', or 'Not Installed'."""
    if not is_windows_service_installed():
        return "Not Installed"
    try:
        status_info = win32serviceutil.QueryServiceStatus("FolderLock")
        state = status_info[1]
        if state == win32service.SERVICE_RUNNING:
            return "Running"
        elif state == win32service.SERVICE_STOPPED:
            return "Stopped"
        elif state == win32service.SERVICE_START_PENDING:
            return "Starting"
        elif state == win32service.SERVICE_STOP_PENDING:
            return "Stopping"
        return f"State({state})"
    except Exception:
        return "Unknown"


if __name__ == "__main__":
    if not PYWIN32_AVAILABLE:
        print("[-] pywin32 is not installed. Install with: python -m pip install pywin32")
        sys.exit(1)
    win32serviceutil.HandleCommandLine(FolderLockWindowsService)
