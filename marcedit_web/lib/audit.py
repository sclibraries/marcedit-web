"""Append-only JSONL audit log for security-relevant events.

The audit log is **write-only** from the app's perspective — we never
read it back. It exists so an operator (or downstream SIEM) can answer
"who uploaded what, when, and was anything rejected?" The format is
one JSON object per line, with a fixed ``ts`` / ``kind`` / ``user``
header plus arbitrary event-specific fields.

Event categories the app emits today (kept aligned with the actual
``audit_event(...)`` callsites):

* ``upload-accepted`` / ``upload-rejected`` (Home, Diff sides,
  Marc Tools)
* ``upload-restored`` (TASK-051 — refresh-resume from SQL row)
* ``tasksfile-imported`` / ``tasksfile-rejected``
* ``archive-imported`` / ``archive-rejected`` (MarcEdit zip path)
* ``sandbox-timeout`` / ``sandbox-nonzero-exit``
* ``task-saved`` / ``task-deleted`` / ``task-visibility-changed``
* ``task-run-completed`` (TASK-034 — carries task names,
  in/out/changed/error counts, returncode, timed_out)
* ``batch-replace-applied`` (Quick find/replace Apply; matched/applied
    /changed counts plus field scope)
* ``conversion-issued`` (TASK-032 — Marc Tools conversion completed;
  kind, source bytes, output bytes)
* ``dedupe-deletes-issued`` (TASK-046 — Dedupe deletes export built;
  strategy + params + groups total + deletes count)
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

TASK-049: events also dual-write to the ``audit_events`` SQL table
in ``data/marcedit.db``. The SQL write happens AFTER the JSONL line
and is independently wrapped — a DB failure can't undo the disk log.
JSONL stays the operator's tail/grep surface; SQL is for analyst
queries. The JSONL path will go away in a future ticket once SQL
has proven stable in operation.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from . import db, runmode

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
    """Append one JSONL event line and one SQL row for this event.

    Always non-blocking from the caller's perspective. The header
    fields (``ts`` UTC ISO-8601, ``kind``, ``user``) are emitted in a
    stable order so log-grep-style consumers stay simple.

    Both writes (JSONL + SQL) are independently wrapped so a failure
    in either path can't take down the user's action. JSONL is the
    operator's tail/grep surface; SQL is the analyst's query surface.
    """
    ts = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    payload: dict[str, Any] = {"ts": ts, "kind": kind, "user": user}
    payload.update(fields)
    try:
        line = json.dumps(payload, sort_keys=True, default=str) + "\n"
        with _lock:
            with _audit_path().open("a", encoding="utf-8") as f:
                f.write(line)
    except OSError as exc:
        logger.warning("audit-write failed for %s: %s", kind, exc)

    # SQL mirror — private mode only. Public-tier processes never touch
    # the catalog DB; the guard here enforces that in code, not just via
    # a read-only filesystem mount. Independent of JSONL so a DB hiccup
    # can't lose the on-disk trail. ``payload_json`` carries everything
    # except the indexed columns; that lets reporters reconstruct each
    # event without joining tables.
    if runmode.is_private():
        try:
            # Idempotent; in-process flag short-circuits after first call.
            # Doing it here means callers that audit before App.py boots
            # (e.g. tests, ad-hoc scripts) don't trip "no such table".
            db.init_schema()
            sql_fields = {k: v for k, v in payload.items() if k not in {"ts", "kind", "user"}}
            payload_json = json.dumps(sql_fields, sort_keys=True, default=str)
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO audit_events(ts, user_email, kind, payload_json)"
                    " VALUES (?, ?, ?, ?)",
                    (ts, user, kind, payload_json),
                )
        except Exception as exc:  # noqa: BLE001 — audit must never propagate
            logger.warning("audit-sql-write failed for %s: %s", kind, exc)
