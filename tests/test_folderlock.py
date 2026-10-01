"""
test_folderlock.py - Verification test suite for FolderLock core engine.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from folderlock_core import (
    lock_folder,
    unlock_folder,
    is_folder_locked,
    verify_vault_password,
    InvalidPasswordError,
    FolderLockError,
    VAULT_FILENAME,
    README_FILENAME
)


class TestFolderLockCore(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="flock_test_")
        self.test_path = Path(self.test_dir)

        # Create test folder structure
        self.sub_dir = self.test_path / "documents" / "personal"
        self.sub_dir.mkdir(parents=True)

        self.file1 = self.test_path / "hello.txt"
        self.file1.write_text("Hello World! This is secret text 12345.", encoding="utf-8")

        self.file2 = self.sub_dir / "secret_finance.csv"
        self.file2.write_text("account,amount\n12345,99999\n", encoding="utf-8")

        self.file3 = self.test_path / "binary_data.bin"
        self.file3.write_bytes(os.urandom(1024 * 50))  # 50 KB binary file

        self.password = "MySuperSecretMasterPass!2026"

    def tearDown(self):
        from folderlock_core import set_folder_access_denied
        set_folder_access_denied(self.test_path, False)
        if os.path.exists(self.test_dir):
            try:
                shutil.rmtree(self.test_dir)
            except Exception:
                pass

    def test_lock_and_unlock_cycle(self):
        # 1. Folder is initially not locked
        self.assertFalse(is_folder_locked(str(self.test_path)))

        # 2. Lock folder
        result = lock_folder(str(self.test_path), self.password)
        self.assertEqual(result["status"], "locked")
        self.assertTrue(is_folder_locked(str(self.test_path)))

        # 3. Check that plain files are gone / denied
        self.assertFalse(self.file1.exists())
        self.assertFalse(self.file2.exists())
        self.assertFalse(self.file3.exists())
        self.assertFalse(self.sub_dir.exists())

        # 4. Verify password verification function works while locked
        self.assertTrue(verify_vault_password(str(self.test_path), self.password))
        self.assertFalse(verify_vault_password(str(self.test_path), "WrongPassword123"))

        # 5. Unlock with wrong password should fail
        with self.assertRaises(InvalidPasswordError):
            unlock_folder(str(self.test_path), "WrongPassword123")

        self.assertFalse(self.file1.exists())

        # 6. Unlock with correct password
        unlock_result = unlock_folder(str(self.test_path), self.password)
        self.assertEqual(unlock_result["status"], "unlocked")
        self.assertFalse(is_folder_locked(str(self.test_path)))

        # 7. Check that files are completely restored with exact content
        self.assertTrue(self.file1.exists())
        self.assertEqual(self.file1.read_text(encoding="utf-8"), "Hello World! This is secret text 12345.")

        self.assertTrue(self.file2.exists())
        self.assertEqual(self.file2.read_text(encoding="utf-8"), "account,amount\n12345,99999\n")

        self.assertTrue(self.file3.exists())
        self.assertEqual(len(self.file3.read_bytes()), 1024 * 50)

        # 8. Check that vault and README are cleaned up
        self.assertFalse((self.test_path / VAULT_FILENAME).exists())
        self.assertFalse((self.test_path / README_FILENAME).exists())

    def test_tampering_detection(self):
        from folderlock_core import VaultCorruptedError, clear_file_attributes, set_folder_access_denied
        # Lock folder
        lock_folder(str(self.test_path), self.password)
        set_folder_access_denied(self.test_path, False)
        vault_file = self.test_path / VAULT_FILENAME

        # Corrupt the ciphertext bytes near the end
        clear_file_attributes(vault_file)
        data = bytearray(vault_file.read_bytes())
        data[-10] ^= 0xFF  # Flip bits in ciphertext or tag
        vault_file.write_bytes(data)

        # Attempting unlock should detect tampering and raise VaultCorruptedError
        with self.assertRaises(VaultCorruptedError):
            unlock_folder(str(self.test_path), self.password)

    def test_unicode_and_spaces(self):
        # Create folder with unicode and spaces
        unicode_dir = self.test_path / "📁 Projets Spéciaux 🔒"
        unicode_dir.mkdir()
        unicode_file = unicode_dir / "résumé_財務_レポート.txt"
        unicode_file.write_text("Données confidentielles / 機密データ", encoding="utf-8")

        lock_folder(str(self.test_path), self.password)
        self.assertTrue(is_folder_locked(str(self.test_path)))

        unlock_folder(str(self.test_path), self.password)
        self.assertTrue(unicode_file.exists())
        self.assertEqual(unicode_file.read_text(encoding="utf-8"), "Données confidentielles / 機密データ")

    def test_modify_after_unlock_and_relock(self):
        # Lock then unlock
        lock_folder(str(self.test_path), self.password)
        unlock_folder(str(self.test_path), self.password)

        # User adds a new file
        new_file = self.test_path / "newly_added_doc.txt"
        new_file.write_text("Newly added confidential notes", encoding="utf-8")

        # Relock with a different password
        new_password = "NewDifferentPassword789!"
        lock_folder(str(self.test_path), new_password)
        self.assertTrue(is_folder_locked(str(self.test_path)))
        self.assertFalse(new_file.exists())

        # Old password should not work
        self.assertFalse(verify_vault_password(str(self.test_path), self.password))
        self.assertTrue(verify_vault_password(str(self.test_path), new_password))

        # Unlock with new password
        unlock_folder(str(self.test_path), new_password)
        self.assertTrue(new_file.exists())
        self.assertEqual(new_file.read_text(encoding="utf-8"), "Newly added confidential notes")


if __name__ == "__main__":
    unittest.main()

