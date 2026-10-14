"""
samba_client.py 
Opérations SMB2/3 : list, upload, stream, delete, preview.
require_encryption=True -- compatible smb encrypt = required sur le serveur.
"""

import os
import uuid
import datetime
from contextlib import contextmanager
from smbprotocol.connection import Connection
from smbprotocol.session import Session
from smbprotocol.tree import TreeConnect
from smbprotocol.open import (
    Open, CreateDisposition, CreateOptions,
    FileAttributes, FilePipePrinterAccessMask,
    ImpersonationLevel, ShareAccess,
)
from smbprotocol import exceptions as smb_exc

SAMBA_SERVER = os.getenv("SAMBA_SERVER", "10.0.1.10")
SAMBA_DOMAIN = os.getenv("SAMBA_DOMAIN", "WORKGROUP")
CHUNK_SIZE   = 65536  # 64 Ko

GROUP_SHARES = {
    "direction":    ["direction", "commun"],
    "comptabilite": ["comptabilite", "commun"],
    "rh":           ["rh", "commun"],
    "technique":    ["technique", "commun"],
}

PREVIEW_TEXT  = {".txt", ".log", ".conf", ".sh", ".py", ".md", ".csv", ".ini", ".xml", ".json", ".yaml", ".yml"}
PREVIEW_IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
PREVIEW_PDF   = {".pdf"}

# Share mode used for every open: we always allow delete, so a handle left
# open by a read/preview never blocks a later delete with a sharing violation.
_SHARE_RWD = (ShareAccess.FILE_SHARE_READ
              | ShareAccess.FILE_SHARE_WRITE
              | ShareAccess.FILE_SHARE_DELETE)


# Connexion
@contextmanager
def _smb(share: str | None, username: str, password: str):
    """
    Ouvre une session SMB2/3 chiffrée (+ un partage si `share` est fourni)
    et garantit la fermeture de la session et de la connexion, même en cas
    d'erreur (sinon les handles restent ouverts côté serveur -> conflits).
    """
    conn = session = tree = None
    try:
        conn = Connection(uuid.uuid4(), SAMBA_SERVER, 445)
        conn.connect()
        session = Session(conn, username, password, require_encryption=True)
        session.connect()
        if share:
            tree = TreeConnect(session, f"\\\\{SAMBA_SERVER}\\{share}")
            tree.connect()
        yield tree
    finally:
        for obj in (tree, session, conn):
            try:
                if obj is not None:
                    obj.disconnect()
            except Exception:
                pass


def _format_size(n: int) -> str:
    if n < 1024:        return f"{n} o"
    elif n < 1_048_576: return f"{n // 1024} Ko"
    else:               return f"{n / 1_048_576:.1f} Mo"


def _filetime_to_str(ft: int) -> str:
    try:
        dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return "-"


def _decode_name(raw) -> str:
    """SMB returns file names as raw UTF-16LE bytes; decode to str."""
    if isinstance(raw, bytes):
        return raw.decode("utf-16-le", errors="replace")
    return raw


def _smb_error(e: Exception) -> str:
    """Turn a low-level SMB exception into a clean, user-facing message."""
    s = str(e)
    if "LOGON_FAILURE" in s or "WRONG_PASSWORD" in s:
        return "Incorrect username or password."
    if "ACCESS_DENIED" in s:
        return "Permission denied for this action."
    if "OBJECT_PATH_NOT_FOUND" in s or "OBJECT_NAME_NOT_FOUND" in s:
        return "This file no longer exists on the server."
    if "OBJECT_NAME_COLLISION" in s:
        return "A file with this name already exists."
    if "DISK_FULL" in s:
        return "The server's disk is full."
    if "SHARING_VIOLATION" in s or "FILE_LOCK_CONFLICT" in s:
        return "This file is currently open by someone else."
    if "NOT_SUPPORTED" in s or "NOT_IMPLEMENTED" in s:
        return "This operation is not supported by the server."
    return "The server refused the operation."


# Auth
def test_auth(username: str, password: str) -> dict:
    try:
        with _smb(None, username, password):
            pass
        group = _detect_group(username, password)
        return {"ok": True, "group": group}
    except smb_exc.SMBAuthenticationError:
        return {"ok": False, "error": "Incorrect username or password."}
    except smb_exc.SMBException as e:
        return {"ok": False, "error": _smb_error(e)}
    except Exception:
        return {"ok": False, "error": "Cannot reach the Samba server. Is the server running?"}


def _detect_group(username: str, password: str) -> str:
    """Détermine le groupe de l'utilisateur en testant l'accès aux partages."""
    for group, shares in GROUP_SHARES.items():
        for share in shares:
            if share == "commun":
                continue
            try:
                with _smb(share, username, password):
                    return group
            except Exception:
                continue
    return "commun"


# Liste des fichiers
def list_files(share: str, username: str, password: str) -> dict:
    try:
        with _smb(share, username, password) as tree:
            dir_open = Open(tree, "")
            dir_open.create(
                ImpersonationLevel.Impersonation,
                FilePipePrinterAccessMask.GENERIC_READ,
                FileAttributes.FILE_ATTRIBUTE_DIRECTORY,
                _SHARE_RWD,
                CreateDisposition.FILE_OPEN,
                CreateOptions.FILE_DIRECTORY_FILE,
            )

            # Constante SMB2_FIND_BOTH_DIRECTORY_INFO = 3
            try:
                raw_files = dir_open.query_directory("*", 3)
            finally:
                dir_open.close()

            files = []
            for f in raw_files:
                name = _decode_name(f["file_name"].get_value())
                if name in (".", ".."):
                    continue

                attrs    = f["file_attributes"].get_value()
                is_dir   = bool(attrs & 0x10)
                size_val = f["end_of_file"].get_value() if not is_dir else 0
                mtime    = f["last_write_time"].get_value()
                ext      = os.path.splitext(name)[1].lower()

                can_preview = (
                    ext in PREVIEW_TEXT
                    or ext in PREVIEW_IMAGE
                    or ext in PREVIEW_PDF
                ) and not is_dir

                files.append({
                    "name":    name,
                    "size":    _format_size(size_val) if not is_dir else "-",
                    "date":    _filetime_to_str(mtime),
                    "is_dir":  is_dir,
                    "ext":     ext,
                    "preview": can_preview,
                })

            # Dossiers en premier, puis fichiers par nom
            files.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
            return {"ok": True, "files": files}

    except smb_exc.SMBAuthenticationError:
        return {"ok": False, "error": "Incorrect username or password."}
    except smb_exc.SMBException as e:
        return {"ok": False, "error": _smb_error(e)}
    except Exception:
        return {"ok": False, "error": f"Cannot reach the Samba server ({SAMBA_SERVER})."}


# Upload
def upload_file(share: str, filename: str, data: bytes,
                username: str, password: str) -> dict:
    try:
        with _smb(share, username, password) as tree:
            file_open = Open(tree, filename)
            file_open.create(
                ImpersonationLevel.Impersonation,
                FilePipePrinterAccessMask.GENERIC_WRITE | FilePipePrinterAccessMask.GENERIC_READ,
                FileAttributes.FILE_ATTRIBUTE_NORMAL,
                _SHARE_RWD,
                CreateDisposition.FILE_OVERWRITE_IF,  # Écrase si existe
                CreateOptions.FILE_NON_DIRECTORY_FILE,
            )

            try:
                # Écriture chunk par chunk
                offset = 0
                while offset < len(data):
                    chunk = data[offset:offset + CHUNK_SIZE]
                    file_open.write(chunk, offset)
                    offset += len(chunk)
                file_open.flush()
            finally:
                file_open.close()

            return {"ok": True}

    except smb_exc.SMBException as e:
        return {"ok": False, "error": _smb_error(e)}
    except Exception:
        return {"ok": False, "error": "Upload failed: cannot reach the Samba server."}


# Taille du fichier
def get_file_size(share: str, filename: str,
                  username: str, password: str) -> int | None:
    """Retourne la taille en octets du fichier, ou None si indéterminable."""
    try:
        with _smb(share, username, password) as tree:
            dirpath  = os.path.dirname(filename)
            basename = os.path.basename(filename)

            dir_open = Open(tree, dirpath)
            dir_open.create(
                ImpersonationLevel.Impersonation,
                FilePipePrinterAccessMask.GENERIC_READ,
                FileAttributes.FILE_ATTRIBUTE_DIRECTORY,
                _SHARE_RWD,
                CreateDisposition.FILE_OPEN,
                CreateOptions.FILE_DIRECTORY_FILE,
            )
            try:
                for entry in dir_open.query_directory(basename, 3):
                    if _decode_name(entry["file_name"].get_value()).lower() == basename.lower():
                        return int(entry["end_of_file"].get_value())
            finally:
                dir_open.close()
            return None
    except Exception:
        return None


# Streaming download
def stream_file(share: str, filename: str,
                username: str, password: str):
    """
    Générateur Python -- yield chunk par chunk 64 Ko.
    Flask envoie chaque chunk immédiatement au navigateur.
    RAM utilisée = 64 Ko max, quel que soit la taille du fichier.
    """
    conn = session = tree = file_open = None
    try:
        conn = Connection(uuid.uuid4(), SAMBA_SERVER, 445)
        conn.connect()
        session = Session(conn, username, password, require_encryption=True)
        session.connect()
        tree = TreeConnect(session, f"\\\\{SAMBA_SERVER}\\{share}")
        tree.connect()

        file_open = Open(tree, filename)
        file_open.create(
            ImpersonationLevel.Impersonation,
            FilePipePrinterAccessMask.GENERIC_READ,
            FileAttributes.FILE_ATTRIBUTE_NORMAL,
            _SHARE_RWD,
            CreateDisposition.FILE_OPEN,
            CreateOptions.FILE_NON_DIRECTORY_FILE,
        )

        offset = 0
        while True:
            try:
                chunk = file_open.read(offset, CHUNK_SIZE)
            except smb_exc.EndOfFile:
                break  # clean end of file
            if not chunk:
                break
            yield chunk
            offset += len(chunk)

    except Exception:
        yield b""  # Fin propre du générateur en cas d'erreur
    finally:
        # Toujours libérer le handle et la session, même si le client coupe
        # la connexion en cours de téléchargement (GeneratorExit).
        try:
            if file_open is not None:
                file_open.close()
        except Exception:
            pass
        for obj in (tree, session, conn):
            try:
                if obj is not None:
                    obj.disconnect()
            except Exception:
                pass


# Prévisualisation texte
def read_text_file(share: str, filename: str,
                   username: str, password: str,
                   max_bytes: int = 1_048_576) -> dict:
    """
    Lit un fichier texte en entier (max 1 Mo).
    Pour les fichiers > 1 Mo, utiliser stream_file à la place.
    """
    try:
        with _smb(share, username, password) as tree:
            file_open = Open(tree, filename)
            file_open.create(
                ImpersonationLevel.Impersonation,
                FilePipePrinterAccessMask.GENERIC_READ,
                FileAttributes.FILE_ATTRIBUTE_NORMAL,
                _SHARE_RWD,
                CreateDisposition.FILE_OPEN,
                CreateOptions.FILE_NON_DIRECTORY_FILE,
            )

            try:
                data = b""
                offset = 0
                while True:
                    try:
                        chunk = file_open.read(offset, CHUNK_SIZE)
                    except smb_exc.EndOfFile:
                        break  # clean end of file
                    if not chunk:
                        break
                    data   += chunk
                    offset += len(chunk)
                    if offset >= max_bytes:
                        data += b"\n\n[... truncated: file larger than 1 MB ...]"
                        break
            finally:
                file_open.close()

            content = data.decode("utf-8", errors="replace")
            return {"ok": True, "content": content}

    except smb_exc.SMBException as e:
        return {"ok": False, "error": _smb_error(e)}
    except Exception:
        return {"ok": False, "error": "Unable to read this file."}


# Suppression
def delete_file(share: str, filename: str,
                username: str, password: str) -> dict:
    try:
        with _smb(share, username, password) as tree:
            file_open = Open(tree, filename)
            file_open.create(
                ImpersonationLevel.Impersonation,
                FilePipePrinterAccessMask.DELETE,
                FileAttributes.FILE_ATTRIBUTE_NORMAL,
                ShareAccess.FILE_SHARE_DELETE,
                CreateDisposition.FILE_OPEN,
                CreateOptions.FILE_NON_DIRECTORY_FILE | CreateOptions.FILE_DELETE_ON_CLOSE,
            )
            file_open.close()
        return {"ok": True}

    except smb_exc.SMBException as e:
        return {"ok": False, "error": _smb_error(e)}
    except Exception:
        return {"ok": False, "error": "Unable to delete this file."}
