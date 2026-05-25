"""Append-only JSONL audit log for security-relevant events.

The audit log is **write-only** from the app's perspective — we never
read it back. It exists so an operator (or downstream SIEM) can answer
"who uploaded what, when, and was anything rejected?" The format is
one JSON object per line, with a fixed ``ts`` / ``kind`` / ``user``
header plus arbitrary event-specific fields.

Event categories the app emits today (kept aligned with the actual
``audit_event(...)`` callsites):

* ``upload-accepted`` / ``upload-rejected`` (Home, Diff sides)
* ``tasksfile-imported`` / ``tasksfile-rejected``
* ``archive-imported`` / ``archive-rejected`` (MarcEdit zip path)
* ``sandbox-timeout`` / ``sandbox-nonzero-exit``
* ``task-saved`` / ``task-deleted``
* ``admin-action`` (Code-view save while ``task_admin.is_admin()``)
* ``anonymous-action-refused`` (prod mode, missing identity header)

Downloads of bytes the cataloger already had access to upload are
intentionally **not** audited (Stage 19 scope: security-relevant
events only). If your deployment needs egress logging, layer it at
the reverse-proxy.

Audit IO failures (disk full, permissions) are logged at
``logging.WARNING`` and swallowed — audit must never block the
user-facing operation. A missed audit line is operationally annoying
but not unsafe; a crashed upload because the audit log is
unwriteable would be worse.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("marcedit_web.audit")

# Process-wide lock — Streamlit runs scripts on a thread pool, so two
# pages updating the same audit file at once is plausible. With this
# lock + line-buffered append, every event is a complete JSON line.
_lock = threading.Lock()


def _audit_dir() -> Path:
    base = os.environ.get("MARCEDIT_WEB_AUDIT_DIR", "data/audit")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _audit_path() -> Path:
    # One file per UTC day; ops handles rotation via logrotate or
    # equivalent. Daily granularity is enough for after-the-fact
    # investigation; per-hour files would clutter the directory.
    today = dt.datetime.utcnow().date().isoformat()
    return _audit_dir() / f"audit-{today}.log"


def audit_event(kind: str, *, user: str = "anonymous", **fields: Any) -> None:
    """Append one JSONL event line to today's audit file.

    Always non-blocking from the caller's perspective. The header
    fields (``ts`` UTC ISO-8601, ``kind``, ``user``) are emitted in a
    stable order so log-grep-style consumers stay simple.
    """
    payload: dict[str, Any] = {
        "ts": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "kind": kind,
        "user": user,
    }
    payload.update(fields)
    try:
        line = json.dumps(payload, sort_keys=True, default=str) + "\n"
        with _lock:
            with _audit_path().open("a", encoding="utf-8") as f:
                f.write(line)
    except OSError as exc:
        logger.warning("audit-write failed for %s: %s", kind, exc)
