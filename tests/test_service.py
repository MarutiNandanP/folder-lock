"""
test_service.py - Integration test for FolderLock background service and IPC client.
"""

import os
import time
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from folderlock_service import FolderLockService, FolderLockClient
from folderlock_core import is_folder_locked


class TestFolderLockService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = FolderLockService(port=52199)
        cls.service_thread = threading.Thread(target=cls.service.start, daemon=True)
        cls.service_thread.start()

        # Wait for service to initialize
        for _ in range(30):
            time.sleep(0.1)
            if FolderLockClient.is_service_running():
                break

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="flock_srv_test_")
        self.test_path = Path(self.test_dir)
        self.secret_file = self.test_path / "service_secret.txt"
        self.secret_file.write_text("Confidential service payload 999", encoding="utf-8")
        self.password = "ServiceTestPass#2026"

    def tearDown(self):
        if os.path.exists(self.test_dir):
            try:
                shutil.rmtree(self.test_dir)
            except Exception:
                pass

    def test_service_ping(self):
        res = FolderLockClient.call("ping")
        self.assertTrue(res.get("success"))
        self.assertEqual(res["data"]["status"], "running")

    def test_service_lock_unlock_flow(self):
        # 1. Lock folder via service
        lock_res = FolderLockClient.call("lock_folder", {
            "folder_path": str(self.test_path),
            "password": self.password,
            "auto_lock_minutes": 5
        })
        self.assertTrue(lock_res.get("success"))
        self.assertTrue(is_folder_locked(str(self.test_path)))
        self.assertFalse(self.secret_file.exists())

        # 2. Check vault list
        list_res = FolderLockClient.call("list_vaults")
        self.assertTrue(list_res.get("success"))
        vaults = list_res["data"]
        matching = [v for v in vaults if v["folder_path"] == str(self.test_path)]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0]["is_locked"])

        # 3. Unlock with wrong password
        fail_res = FolderLockClient.call("unlock_folder", {
            "folder_path": str(self.test_path),
            "password": "WrongPassword999",
            "open_explorer": False
        })
        self.assertFalse(fail_res.get("success"))
        self.assertEqual(fail_res.get("error_type"), "invalid_password")

        # 4. Unlock with correct password
        unlock_res = FolderLockClient.call("unlock_folder", {
            "folder_path": str(self.test_path),
            "password": self.password,
            "open_explorer": False
        })
        self.assertTrue(unlock_res.get("success"))
        self.assertFalse(is_folder_locked(str(self.test_path)))
        self.assertTrue(self.secret_file.exists())
        self.assertEqual(self.secret_file.read_text(encoding="utf-8"), "Confidential service payload 999")

    def test_service_auto_lock_timeout(self):
        # Lock then unlock with very short timeout (0.05 min = 3 sec)
        FolderLockClient.call("lock_folder", {
            "folder_path": str(self.test_path),
            "password": self.password,
            "auto_lock_minutes": 0.05
        })
        self.assertTrue(is_folder_locked(str(self.test_path)))

        FolderLockClient.call("unlock_folder", {
            "folder_path": str(self.test_path),
            "password": self.password,
            "auto_lock_minutes": 0.05,
            "open_explorer": False
        })
        self.assertFalse(is_folder_locked(str(self.test_path)))

        # Wait 4 seconds for background service timer to trigger auto-lock
        time.sleep(4.5)

        # It should now be auto-locked!
        self.assertTrue(is_folder_locked(str(self.test_path)))
        self.assertFalse(self.secret_file.exists())


if __name__ == "__main__":
    unittest.main()
