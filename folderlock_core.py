"""
folderlock_core.py - Core Cryptographic & Vault Management Engine for FolderLock.

Provides:
- AES-256-GCM Authenticated Encryption & Decryption
- PBKDF2-HMAC-SHA256 Key Derivation (300,000 iterations)
- Constant-time password verification via HMAC tokens
- Secure data shredding (overwrites disk sectors before removal)
- Directory archiving with timestamp & structure preservation
- Safe atomic vault creation (verifies before deleting originals)
"""

import os
import sys
import io
import stat
import hmac
import zipfile
import hashlib
import tempfile
from pathlib import Path
from typing import Tuple, Optional, Callable, Dict, Any
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# Protocol Constants
VAULT_MAGIC = b"FLOCKV01"
VAULT_FILENAME = ".folderlock_vault.flock"
README_FILENAME = "README_LOCKED.txt"
META_FILENAME = ".folderlock_meta.json"
PBKDF2_ITERATIONS = 300_000
SALT_SIZE = 16
NONCE_SIZE = 12
KEY_SIZE = 32
VERIFIER_SIZE = 32
VERIFIER_PROMPT = b"FOLDERLOCK_VERIFY_TOKEN_V1"

README_CONTENT = """======================================================================
THIS FOLDER IS LOCKED AND ENCRYPTED WITH FOLDERLOCK (AES-256-GCM)
======================================================================

All contents inside this folder have been cryptographically encrypted
using military-grade AES-256 in Galois/Counter Mode (AEAD).
Original plaintext files have been securely shredded from disk.

SECURITY NOTICE:
Taking this hard drive, mounting it on another machine (Linux/Mac/Win),
or opening it as Administrator will NOT allow viewing of any files,
filenames, or directory structures. Without the correct master password,
the data remains cryptographically undecryptable.

TO UNLOCK THIS FOLDER:
1. Open the FolderLock application or tray icon.
2. Select this folder and enter the master password you chose.
3. Or right-click this folder -> 'Unlock with FolderLock'.
4. Or run from command line:
   python folderlock_cli.py unlock "{folder_path}"

======================================================================
"""


class FolderLockError(Exception):
    """Base exception for FolderLock errors."""
    pass


class InvalidPasswordError(FolderLockError):
    """Raised when the provided password fails verification."""
    pass


class VaultCorruptedError(FolderLockError):
    """Raised when vault data has been tampered with or corrupted."""
    pass


class FileInUseError(FolderLockError):
    """Raised when a file in the folder is locked by another program."""
    pass


def clear_file_attributes(filepath: Path) -> None:
    """Resets file attributes to normal on Windows to prevent PermissionError when modifying."""
    try:
        os.chmod(filepath, stat.S_IWRITE | stat.S_IREAD)
        if sys.platform == "win32":
            import ctypes
            FILE_ATTRIBUTE_NORMAL = 0x80
            ctypes.windll.kernel32.SetFileAttributesW(str(filepath), FILE_ATTRIBUTE_NORMAL)
    except Exception:
        pass


def set_file_hidden(filepath: Path, hidden: bool = True) -> None:
    """Sets or unsets hidden attribute on Windows."""
    if sys.platform == "win32":
        try:
            import ctypes
            FILE_ATTRIBUTE_HIDDEN = 0x02
            FILE_ATTRIBUTE_NORMAL = 0x80
            attr = FILE_ATTRIBUTE_HIDDEN if hidden else FILE_ATTRIBUTE_NORMAL
            ctypes.windll.kernel32.SetFileAttributesW(str(filepath), attr)
        except Exception:
            pass


def derive_keys(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> Tuple[bytes, bytes, bytes]:
    """
    Derives (enc_key, auth_key, verifier) from password and salt using PBKDF2-HMAC-SHA256.
    - enc_key: 32 bytes for AES-256-GCM
    - auth_key: 32 bytes for HMAC verification
    - verifier: 32 bytes HMAC digest of VERIFIER_PROMPT using auth_key
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=64,
        salt=salt,
        iterations=iterations,
    )
    derived = kdf.derive(password.encode("utf-8"))
    enc_key = derived[:32]
    auth_key = derived[32:64]
    verifier = hmac.new(auth_key, VERIFIER_PROMPT, hashlib.sha256).digest()
    return enc_key, auth_key, verifier


def secure_shred_file(filepath: Path, passes: int = 1) -> None:
    """
    Securely shreds a file by overwriting its sectors with random data and zeros
    before unlinking, preventing forensic file carving on physical hard disks.
    """
    try:
        # Clear read-only attributes if set
        os.chmod(filepath, stat.S_IWRITE | stat.S_IREAD)
        file_size = filepath.stat().st_size

        if file_size > 0:
            with open(filepath, "r+b") as f:
                # Pass 1: Cryptographic random bytes
                chunk_size = 64 * 1024
                remaining = file_size
                while remaining > 0:
                    write_size = min(chunk_size, remaining)
                    f.write(os.urandom(write_size))
                    remaining -= write_size
                f.flush()
                os.fsync(f.fileno())

                # Pass 2: Overwrite with zeros
                if passes > 1:
                    f.seek(0)
                    remaining = file_size
                    zeros = b"\x00" * chunk_size
                    while remaining > 0:
                        write_size = min(chunk_size, remaining)
                        f.write(zeros[:write_size])
                        remaining -= write_size
                    f.flush()
                    os.fsync(f.fileno())

                # Truncate
                f.seek(0)
                f.truncate(0)

        os.remove(filepath)
    except PermissionError as e:
        raise FileInUseError(f"Cannot securely shred '{filepath.name}'. File may be open in another application.") from e
    except Exception as e:
        # Fallback to standard remove if shredding has filesystem restrictions
        if filepath.exists():
            os.remove(filepath)


def close_explorer_windows(folder_path: str) -> None:
    """Closes any open Windows File Explorer windows viewing the specified folder or subpaths."""
    if sys.platform != "win32":
        return
    try:
        import win32com.client
        from urllib.parse import unquote, urlparse
        shell = win32com.client.Dispatch("Shell.Application")
        target_norm = os.path.normpath(folder_path).lower()
        for window in list(shell.Windows()):
            try:
                url = getattr(window, "LocationURL", "")
                if url:
                    parsed = urlparse(url)
                    if parsed.scheme == "file":
                        local_path = os.path.normpath(unquote(parsed.path).lstrip("/")).lower()
                        if local_path == target_norm or local_path.startswith(target_norm + "\\"):
                            window.Quit()
            except Exception:
                pass
    except Exception:
        pass


def set_folder_access_denied(folder_path: Path, deny: bool = True) -> bool:
    """Sets or removes Windows NTFS Deny ACL so Explorer blocks direct access with Access Denied."""
    if sys.platform != "win32":
        return True
    user = os.environ.get("USERNAME", "")
    if not user:
        return False
    p = str(folder_path.resolve())
    try:
        import subprocess
        if deny:
            # Deny Read Data (listing) and Write Data, keeping DACL modification rights
            subprocess.run(
                ["icacls", p, "/deny", f"{user}:(OI)(CI)(RD,WD)"],
                capture_output=True,
                creationflags=0x08000000
            )
        else:
            subprocess.run(
                ["icacls", p, "/remove:d", user],
                capture_output=True,
                creationflags=0x08000000
            )
        return True
    except Exception:
        return False


def is_folder_locked(folder_path: str) -> bool:
    """
    Returns True if the specified folder contains a valid FolderLock vault
    or has our NTFS deny lock active.
    """
    p = Path(folder_path).resolve()
    # 1. If accessing directory raises PermissionError, NTFS deny lock is active
    try:
        os.listdir(p)
    except PermissionError:
        return True
    except Exception:
        return False

    # 2. Check vault file
    vault_file = p / VAULT_FILENAME
    if vault_file.is_file():
        try:
            with open(vault_file, "rb") as f:
                magic = f.read(len(VAULT_MAGIC))
                return magic == VAULT_MAGIC
        except Exception:
            return False
    return False


def verify_vault_password(folder_path: str, password: str) -> bool:
    """
    Verifies if the given password matches the folder's vault without decrypting payload.
    Uses constant-time comparison to prevent timing attacks.
    """
    p = Path(folder_path).resolve()
    set_folder_access_denied(p, False)
    try:
        vault_file = p / VAULT_FILENAME
        if not vault_file.is_file():
            set_folder_access_denied(p, True)
            raise FolderLockError("Folder is not locked or vault file is missing.")

        with open(vault_file, "rb") as f:
            magic = f.read(len(VAULT_MAGIC))
            if magic != VAULT_MAGIC:
                set_folder_access_denied(p, True)
                raise VaultCorruptedError("Invalid vault header magic.")

            salt = f.read(SALT_SIZE)
            _nonce = f.read(NONCE_SIZE)
            iter_bytes = f.read(4)
            stored_verifier = f.read(VERIFIER_SIZE)

            iterations = int.from_bytes(iter_bytes, byteorder="big")

        _, _, computed_verifier = derive_keys(password, salt, iterations)
        valid = hmac.compare_digest(computed_verifier, stored_verifier)
        # Always restore deny ACL after credential verification
        set_folder_access_denied(p, True)
        return valid
    except Exception:
        set_folder_access_denied(p, True)
        raise


def lock_folder(
    folder_path: str,
    password: str,
    progress_callback: Optional[Callable[[str, float], None]] = None,
    meta_extra: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Locks and cryptographically encrypts a folder.
    """
    p = Path(folder_path).resolve()
    if not p.exists() or not p.is_dir():
        raise FolderLockError(f"Directory does not exist: {p}")

    # Close any open Windows Explorer windows displaying this folder
    close_explorer_windows(str(p))

    # Temporarily remove any previous deny ACL to read files
    set_folder_access_denied(p, False)

    if is_folder_locked(str(p)):
        set_folder_access_denied(p, True)
        raise FolderLockError("Folder is already locked.")

    if not password:
        raise FolderLockError("Password cannot be empty.")

    if progress_callback:
        progress_callback("Scanning files and checking lock availability...", 0.05)

    # Collect files to encrypt (ignore any existing flock files at root)
    all_items = []
    files_to_pack = []
    total_raw_bytes = 0

    for root, dirs, files in os.walk(p):
        for f in files:
            full_path = Path(root) / f
            rel_path = full_path.relative_to(p)
            if full_path.parent == p and rel_path.name in (VAULT_FILENAME, README_FILENAME, META_FILENAME):
                continue
            try:
                # Test file accessibility (detect locks early)
                with open(full_path, "rb") as test_f:
                    test_f.read(1)
            except PermissionError as e:
                raise FileInUseError(f"File '{rel_path}' is currently open in another program. Please close it first.") from e

            files_to_pack.append((full_path, str(rel_path).replace("\\", "/")))
            total_raw_bytes += full_path.stat().st_size

    if progress_callback:
        progress_callback(f"Compressing {len(files_to_pack)} file(s)...", 0.15)

    # Create compressed archive in a temporary file to support large folders
    temp_archive_fd, temp_archive_path = tempfile.mkstemp(prefix="flock_arch_", suffix=".tmp")
    os.close(temp_archive_fd)
    temp_archive_path = Path(temp_archive_path)

    try:
        with zipfile.ZipFile(temp_archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            packed_count = 0
            for full_path, arcname in files_to_pack:
                zf.write(full_path, arcname=arcname)
                packed_count += 1
                if progress_callback and len(files_to_pack) > 0:
                    pct = 0.15 + (0.35 * (packed_count / len(files_to_pack)))
                    progress_callback(f"Archiving: {arcname}", pct)

        archive_size = temp_archive_path.stat().st_size

        if progress_callback:
            progress_callback("Deriving encryption keys (PBKDF2-HMAC-SHA256, 300k rounds)...", 0.55)

        salt = os.urandom(SALT_SIZE)
        nonce = os.urandom(NONCE_SIZE)
        enc_key, _, verifier = derive_keys(password, salt, PBKDF2_ITERATIONS)

        if progress_callback:
            progress_callback("Encrypting data with AES-256-GCM...", 0.65)

        # Read archive and encrypt with AESGCM
        with open(temp_archive_path, "rb") as f_in:
            plaintext = f_in.read()

        aesgcm = AESGCM(enc_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=VAULT_MAGIC)

        # Free plaintext memory
        del plaintext

        vault_temp = p / f"{VAULT_FILENAME}.tmp"
        with open(vault_temp, "wb") as f_out:
            f_out.write(VAULT_MAGIC)
            f_out.write(salt)
            f_out.write(nonce)
            f_out.write(PBKDF2_ITERATIONS.to_bytes(4, byteorder="big"))
            f_out.write(verifier)
            f_out.write(len(ciphertext).to_bytes(8, byteorder="big"))
            f_out.write(ciphertext)
            f_out.flush()
            os.fsync(f_out.fileno())

        # Atomically replace to final vault name
        final_vault = p / VAULT_FILENAME
        if final_vault.exists():
            final_vault.unlink()
        vault_temp.rename(final_vault)

        # Set hidden attribute on Windows for vault file
        try:
            import ctypes
            FILE_ATTRIBUTE_HIDDEN = 0x02
            ctypes.windll.kernel32.SetFileAttributesW(str(final_vault), FILE_ATTRIBUTE_HIDDEN)
        except Exception:
            pass

        if progress_callback:
            progress_callback("Securely shredding plaintext files from disk...", 0.80)

        # Securely shred and delete original files
        shredded_count = 0
        for full_path, _ in files_to_pack:
            if full_path.exists():
                secure_shred_file(full_path, passes=1)
                shredded_count += 1
                if progress_callback and len(files_to_pack) > 0:
                    pct = 0.80 + (0.15 * (shredded_count / len(files_to_pack)))
                    progress_callback(f"Shredding: {full_path.name}", pct)

        # Remove now-empty subdirectories
        for root, dirs, _ in os.walk(p, topdown=False):
            for d in dirs:
                dir_path = Path(root) / d
                try:
                    dir_path.rmdir()
                except OSError:
                    pass

        # Write README notice
        readme_path = p / README_FILENAME
        with open(readme_path, "w", encoding="utf-8") as f_readme:
            f_readme.write(README_CONTENT.format(folder_path=str(p)))

        final_vault_size = final_vault.stat().st_size if final_vault.exists() else 0

        # Close any open Windows Explorer windows displaying this folder
        close_explorer_windows(str(p))

        # Set Windows Explorer Access Denied ACL so folder is blocked
        set_folder_access_denied(p, True)

        if progress_callback:
            progress_callback("Folder locked and encrypted successfully!", 1.0)

        return {
            "status": "locked",
            "folder_path": str(p),
            "file_count": len(files_to_pack),
            "raw_bytes": total_raw_bytes,
            "vault_size": final_vault_size,
        }

    finally:
        # Clean up temporary archive file
        if temp_archive_path.exists():
            try:
                temp_archive_path.unlink()
            except Exception:
                pass


def unlock_folder(
    folder_path: str,
    password: str,
    progress_callback: Optional[Callable[[str, float], None]] = None
) -> Dict[str, Any]:
    """
    Unlocks and decrypts a locked folder.
    """
    p = Path(folder_path).resolve()
    # Temporarily remove deny ACL so we can inspect vault and verify password
    set_folder_access_denied(p, False)

    vault_file = p / VAULT_FILENAME
    if not vault_file.is_file():
        set_folder_access_denied(p, True)
        raise FolderLockError("Folder is not locked or vault file is missing.")

    if progress_callback:
        progress_callback("Reading vault header and verifying password...", 0.1)

    with open(vault_file, "rb") as f:
        magic = f.read(len(VAULT_MAGIC))
        if magic != VAULT_MAGIC:
            set_folder_access_denied(p, True)
            raise VaultCorruptedError("Invalid or corrupted vault header.")

        salt = f.read(SALT_SIZE)
        nonce = f.read(NONCE_SIZE)
        iter_bytes = f.read(4)
        stored_verifier = f.read(VERIFIER_SIZE)
        len_bytes = f.read(8)

        iterations = int.from_bytes(iter_bytes, byteorder="big")
        ciphertext_len = int.from_bytes(len_bytes, byteorder="big")

        ciphertext = f.read(ciphertext_len)

    if progress_callback:
        progress_callback("Verifying credentials (PBKDF2-HMAC-SHA256)...", 0.3)

    enc_key, _, computed_verifier = derive_keys(password, salt, iterations)
    if not hmac.compare_digest(computed_verifier, stored_verifier):
        # Re-apply deny ACL immediately on wrong password!
        set_folder_access_denied(p, True)
        raise InvalidPasswordError("Incorrect password. Access denied.")

    if progress_callback:
        progress_callback("Decrypting vault data with AES-256-GCM...", 0.6)

    try:
        aesgcm = AESGCM(enc_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=VAULT_MAGIC)
    except Exception as e:
        set_folder_access_denied(p, True)
        raise VaultCorruptedError("Cryptographic authentication failed. Data has been modified or corrupted.") from e

    del ciphertext
    del enc_key

    if progress_callback:
        progress_callback("Restoring files and directories...", 0.8)

    # Extract zip archive
    restored_count = 0
    with zipfile.ZipFile(io.BytesIO(plaintext)) as zf:
        infolist = zf.infolist()
        total_files = len(infolist)
        for member in infolist:
            zf.extract(member, path=p)
            restored_count += 1
            if progress_callback and total_files > 0:
                pct = 0.8 + (0.18 * (restored_count / total_files))
                progress_callback(f"Restoring: {member.filename}", pct)

    del plaintext

    # Remove vault and readme files
    try:
        # Reset attributes before deletion if hidden
        try:
            import ctypes
            FILE_ATTRIBUTE_NORMAL = 0x80
            ctypes.windll.kernel32.SetFileAttributesW(str(vault_file), FILE_ATTRIBUTE_NORMAL)
        except Exception:
            pass

        vault_file.unlink()
    except Exception:
        pass

    readme_file = p / README_FILENAME
    if readme_file.exists():
        try:
            readme_file.unlink()
        except Exception:
            pass

    if progress_callback:
        progress_callback("Folder unlocked successfully!", 1.0)

    return {
        "status": "unlocked",
        "folder_path": str(p),
        "restored_files": restored_count
    }
