"""
samba_client.py 
Opérations SMB2/3 : list, upload, stream, delete, preview.
require_encryption=True -- compatible smb encrypt = required sur le serveur.
"""

import os
import uuid
import datetime
from smbprotocol.connection import Connection
from smbprotocol.session import Session
from smbprotocol.tree import TreeConnect
from smbprotocol.open import (
    Open, CreateDisposition, CreateOptions,
    FileAttributes, FilePipePrinterAccessMask,
    ImpersonationLevel, ShareAccess,
)
from smbprotocol import exceptions as smb_exc

SAMBA_SERVER = os.getenv("SAMBA_SERVER", "192.168.0.119")
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


# Connexion 
def _get_connection(username: str, password: str):
    """Connexion SMB2/3 chiffrée -- compatible smb encrypt = required."""
    conn = Connection(uuid.uuid4(), SAMBA_SERVER, 445)
    conn.connect()
    session = Session(conn, username, password, require_encryption=True)
    session.connect()
    return conn, session


def _format_size(n: int) -> str:
    if n < 1024:        return f"{n} o"
    elif n < 1_048_576: return f"{n // 1024} Ko"
    else:               return f"{n / 1_048_576:.1f} Mo"


def _filetime_to_str(ft: int) -> str:
    try:
        dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return "—"


# Auth
def test_auth(username: str, password: str) -> dict:
    try:
        conn, session = _get_connection(username, password)
        session.disconnect(); conn.disconnect()
        group = _detect_group(username, password)
        return {"ok": True, "group": group}
    except smb_exc.SMBAuthenticationError:
        return {"ok": False, "error": "Identifiant ou mot de passe incorrect (STATUS_LOGON_FAILURE)"}
    except smb_exc.SMBException as e:
        return {"ok": False, "error": f"Erreur SMB : {str(e)}"}
    except Exception as e:
        return {"ok": False, "error": f"Serveur inaccessible : {str(e)}"}


def _detect_group(username: str, password: str) -> str:
    """Détermine le groupe de l'utilisateur en testant l'accès aux partages."""
    for group, shares in GROUP_SHARES.items():
        for share in shares:
            if share == "commun":
                continue
            try:
                conn, session = _get_connection(username, password)
                tree = TreeConnect(session, f"\\\\{SAMBA_SERVER}\\{share}")
                tree.connect()
                tree.disconnect(); session.disconnect(); conn.disconnect()
                return group
            except Exception:
                try:
                    session.disconnect()
                    conn.disconnect()
                except Exception:
                    pass
    return "commun"


# Liste des fichiers
def list_files(share: str, username: str, password: str) -> dict:
    try:
        conn, session = _get_connection(username, password)
        tree = TreeConnect(session, f"\\\\{SAMBA_SERVER}\\{share}")
        tree.connect()

        dir_open = Open(tree, "")
        dir_open.create(
            ImpersonationLevel.Impersonation,
            FilePipePrinterAccessMask.GENERIC_READ,
            FileAttributes.FILE_ATTRIBUTE_DIRECTORY,
            ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE,
            CreateDisposition.FILE_OPEN,
            CreateOptions.FILE_DIRECTORY_FILE,
        )

        # Constante SMB2_FIND_BOTH_DIRECTORY_INFO = 3
        raw_files = dir_open.query_directory("*", 3)
        dir_open.close()

        files = []
        for f in raw_files:
            name = f["file_name"].get_value()
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
                "size":    _format_size(size_val) if not is_dir else "—",
                "date":    _filetime_to_str(mtime),
                "is_dir":  is_dir,
                "ext":     ext,
                "preview": can_preview,
            })

        # Dossiers en premier, puis fichiers par nom
        files.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

        tree.disconnect()
        session.disconnect()
        conn.disconnect()
        return {"ok": True, "files": files}

    except smb_exc.SMBAuthenticationError:
        return {"ok": False, "error": "NT_STATUS_LOGON_FAILURE — identifiants incorrects"}
    except smb_exc.SMBException as e:
        s = str(e)
        if "ACCESS_DENIED" in s:
            return {"ok": False, "error": "NT_STATUS_ACCESS_DENIED — permissions insuffisantes"}
        return {"ok": False, "error": f"Erreur SMB : {s}"}
    except Exception as e:
        return {"ok": False, "error": f"Connexion impossible à {SAMBA_SERVER} : {str(e)}"}


# Upload
def upload_file(share: str, filename: str, data: bytes,
                username: str, password: str) -> dict:
    try:
        conn, session = _get_connection(username, password)
        tree = TreeConnect(session, f"\\\\{SAMBA_SERVER}\\{share}")
        tree.connect()

        file_open = Open(tree, filename)
        file_open.create(
            ImpersonationLevel.Impersonation,
            FilePipePrinterAccessMask.GENERIC_WRITE | FilePipePrinterAccessMask.GENERIC_READ,
            FileAttributes.FILE_ATTRIBUTE_NORMAL,
            ShareAccess.FILE_SHARE_READ,
            CreateDisposition.FILE_OVERWRITE_IF,  # Écrase si existe
            CreateOptions.FILE_NON_DIRECTORY_FILE,
        )

        # Écriture chunk par chunk
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + CHUNK_SIZE]
            file_open.write(chunk, offset)
            offset += len(chunk)

        file_open.flush()
        file_open.close()
        tree.disconnect(); session.disconnect(); conn.disconnect()
        return {"ok": True}

    except smb_exc.SMBException as e:
        return {"ok": False, "error": f"Erreur SMB upload : {str(e)}"}
    except Exception as e:
        return {"ok": False, "error": f"Erreur upload : {str(e)}"}


# Taille du fichier
def get_file_size(share: str, filename: str,
                  username: str, password: str) -> int | None:
    """Retourne la taille en octets du fichier, ou None en cas d'erreur."""
    try:
        conn, session = _get_connection(username, password)
        tree = TreeConnect(session, f"\\\\{SAMBA_SERVER}\\{share}")
        tree.connect()

        f = Open(tree, filename)
        f.create(
            ImpersonationLevel.Impersonation,
            FilePipePrinterAccessMask.GENERIC_READ,
            FileAttributes.FILE_ATTRIBUTE_NORMAL,
            ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE,
            CreateDisposition.FILE_OPEN,
            CreateOptions.FILE_NON_DIRECTORY_FILE,
        )
        # FILE_STANDARD_INFORMATION = 5
        info  = f.query_info(info_class=5, info_type=1, output_buffer_length=24)
        size  = int.from_bytes(info[8:16], "little")
        f.close()
        tree.disconnect(); session.disconnect(); conn.disconnect()
        return size
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
    conn    = None
    session = None
    try:
        conn, session = _get_connection(username, password)
        tree = TreeConnect(session, f"\\\\{SAMBA_SERVER}\\{share}")
        tree.connect()

        file_open = Open(tree, filename)
        file_open.create(
            ImpersonationLevel.Impersonation,
            FilePipePrinterAccessMask.GENERIC_READ,
            FileAttributes.FILE_ATTRIBUTE_NORMAL,
            ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE,
            CreateDisposition.FILE_OPEN,
            CreateOptions.FILE_NON_DIRECTORY_FILE,
        )

        offset = 0
        while True:
            chunk = file_open.read(offset, CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
            offset += len(chunk)

        file_open.close()
        tree.disconnect()

    except Exception as e:
        yield b""  # Fin propre du générateur en cas d'erreur
    finally:
        try:
            if session: session.disconnect()
            if conn:    conn.disconnect()
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
        conn, session = _get_connection(username, password)
        tree = TreeConnect(session, f"\\\\{SAMBA_SERVER}\\{share}")
        tree.connect()

        file_open = Open(tree, filename)
        file_open.create(
            ImpersonationLevel.Impersonation,
            FilePipePrinterAccessMask.GENERIC_READ,
            FileAttributes.FILE_ATTRIBUTE_NORMAL,
            ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE,
            CreateDisposition.FILE_OPEN,
            CreateOptions.FILE_NON_DIRECTORY_FILE,
        )

        data = b""
        offset = 0
        while True:
            chunk = file_open.read(offset, CHUNK_SIZE)
            if not chunk:
                break
            data   += chunk
            offset += len(chunk)
            if offset >= max_bytes:
                data += b"\n\n[... fichier tronqué à 1 Mo ...]"
                break

        file_open.close()
        tree.disconnect(); session.disconnect(); conn.disconnect()

        content = data.decode("utf-8", errors="replace")
        return {"ok": True, "content": content}

    except smb_exc.SMBException as e:
        return {"ok": False, "error": f"Erreur SMB : {str(e)}"}
    except Exception as e:
        return {"ok": False, "error": f"Lecture impossible : {str(e)}"}


# Suppression
def delete_file(share: str, filename: str,
                username: str, password: str) -> dict:
    try:
        conn, session = _get_connection(username, password)
        tree = TreeConnect(session, f"\\\\{SAMBA_SERVER}\\{share}")
        tree.connect()

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
        tree.disconnect(); session.disconnect(); conn.disconnect()
        return {"ok": True}

    except smb_exc.SMBException as e:
        s = str(e)
        if "ACCESS_DENIED" in s:
            return {"ok": False, "error": "NT_STATUS_ACCESS_DENIED — vous n'êtes pas propriétaire"}
        return {"ok": False, "error": f"Erreur SMB : {s}"}
    except Exception as e:
        return {"ok": False, "error": f"Suppression impossible : {str(e)}"}
