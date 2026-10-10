"""
Role
----
Flask side of the UEBA pipeline (SambaPME web portal).

Sources the events stream that ``model/ueba/daemon.py`` consumes:

* ``@lf2r`` decorator: logs portal file operations (download / preview /
  delete) automatically at the Flask boundary.
* ``record_flask_event``: explicit call for routes that need richer metadata
  (e.g. upload with the real byte count).

LF2r / Log-Forgery prevention
-----------------------------
The identity that goes into a log line is taken from the SESSION
(``session["username"]``) -- set server-side at login -- NEVER from
client-supplied values (query string, POST body, path). The action label is
fixed at decoration time: a client can not claim to have performed any other
action than the developer attached to a given route.
"""

import json
import os
import threading
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request, session

EVENTS_FILE = os.getenv("UEBA_EVENTS_FILE", "/var/log/samba_ueba/events.jsonl")
ALERTS_FILE = os.getenv("UEBA_ALERTS_FILE", "/var/log/samba_ueba/ueba.jsonl")
_LOCK = threading.Lock()

ueba_bp = Blueprint("ueba", __name__, url_prefix="/api/ueba")


def _session_identity() -> dict:
    """Server-side identity (LF2r): user comes from the session only."""
    return {
        "user": session.get("username"),
        "group": session.get("group"),
    }


def _write_event(event: dict) -> None:
    """Append one JSONL line (atomic append under a module lock)."""
    Path(EVENTS_FILE).parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, open(EVENTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def record_flask_event(action: str, share: str, filename: str = None,
                       size_bytes: int = None, protocol: str = "flask") -> None:
    """Emit one UEBA event from an explicit call site (e.g. upload)."""
    identity = _session_identity()
    event = {
        "timestamp": _utcnow(),
        "user": identity.get("user"),
        "group": identity.get("group"),
        "protocol": protocol,
        "action": action,
        "file_name": filename or "",
        "extension": Path(filename or "").suffix.lstrip(".").lower(),
        "bytes": size_bytes or 0,
        "share": f"/{share.strip('/')}",
    }
    _write_event(event)


def lf2r(action: str):
    """
    Decorator logging a portal file operation after a successful dispatch.

    The ``share``/``filename`` come from the route's own view args -- the
    same values the handler used -- and the user from the session. Only the
    success case is logged (``abort`` / exceptions bubble up untouched).

    Usage::

        @app.route("/stream/<share>/<path:filename>")
        @login_required
        @lf2r("download")     # <-- below login_required so session exists
        def stream_download(share, filename): ...
    """
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            view = request.view_args or {}
            share = view.get("share")
            fname = view.get("filename")
            resp = fn(*args, **kwargs)
            if _recordable(action, resp):
                record_flask_event(action, share, fname,
                                   size_bytes=_content_length(resp))
            return resp
        return wrapper
    return deco


def _recordable(action: str, resp) -> bool:
    """2xx counts; 3xx only for ``delete`` (its success path is a redirect).

    download/preview answer 200 on success and redirect on error, so their
    302s must NOT be logged; delete ALWAYS redirects after a successful op.
    """
    if resp is None:
        return False
    if isinstance(resp, tuple):
        resp = resp[0]
    code = getattr(resp, "status_code", 500)
    if 200 <= code < 300:
        return True
    return action == "delete" and 300 <= code < 400


def _content_length(resp) -> int | None:
    """Best-effort byte count from a Flask Response (None if unknown)."""
    if resp is None:
        return None
    if isinstance(resp, tuple):
        resp = resp[0]
    length = getattr(resp, "headers", {}).get("Content-Length")
    try:
        return int(length) if length else None
    except (TypeError, ValueError):
        return None


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@ueba_bp.route("/flags")
def flags():
    """Return the last alerts emitted by the daemon (frontend polling)."""
    if not os.path.exists(ALERTS_FILE):
        return jsonify({"alerts": []})
    lines = []
    with open(ALERTS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return jsonify({"alerts": lines[-20:]})


@ueba_bp.route("/events")
def events_tail():
    """Return the last raw events recorded by the portal (debug helper)."""
    if not os.path.exists(EVENTS_FILE):
        return jsonify({"events": []})
    lines = []
    with open(EVENTS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return jsonify({"events": lines[-50:]})