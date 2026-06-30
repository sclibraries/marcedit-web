"""SQLite database foundation for marcedit-web (TASK-049).

One process-wide database file at ``data/marcedit.db`` (override via
``MARCEDIT_WEB_DB_PATH``) backs three persistence features:

* **Audit events** (this ticket) — mirror of the JSONL audit log,
  queryable for incident response.
* **Tasks** (TASK-050) — replaces filesystem-per-user task storage,
  adds a private/shared visibility flag.
* **Uploads** (TASK-051) — per-OAuth-user upload references that
  survive browser refresh.

Design choices worth knowing:

* **Connection-per-call.** Streamlit runs scripts on a thread pool
  and SQLite's default connection isn't safe to share across threads.
  Opening a fresh connection per call is cheap on SQLite and removes
  the lifecycle headache.
* **WAL mode.** Enabled once at ``init_schema()``. Readers don't
  block writers and vice versa; matters because the audit table is
  written from every page render.
* **Schema versioning.** ``_schema_version`` row tracked from day
  one so future tickets can do real migrations. This ticket sets it
  to 1.
* **Stdlib only.** No SQLAlchemy. Three tables and parameterized
  queries don't justify the dep.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger("marcedit_web.db")

SCHEMA_VERSION = 8

SHARED_OWNER_SENTINEL = "__shared__"

_init_lock = threading.Lock()
_initialized = False


def db_path() -> Path:
    """Resolved SQLite file path.

    Default is ``data/marcedit.db`` relative to the process CWD
    (``/app`` in the container). Override with ``MARCEDIT_WEB_DB_PATH``
    for tests or alternate deployments.
    """
    return Path(os.environ.get("MARCEDIT_WEB_DB_PATH", "data/marcedit.db"))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a fresh SQLite connection scoped to this ``with`` block.

    Commits on normal exit; rolls back on exception. ``row_factory``
    is set so callers get column access by name. Foreign-key
    enforcement is enabled on every connection (SQLite defaults to
    off, per-connection).
    """
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _split_env_csv(name: str) -> list[str]:
    """Parse a comma-separated env var into lowercased, stripped, non-empty items."""
    raw = os.environ.get(name, "")
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def _seed_access_control(conn: sqlite3.Connection) -> None:
    """Seed bootstrap admins + allowed domains from env (TASK-088).

    Idempotent and promotion-only: a configured admin email is upserted
    to ``approved``/``admin`` (upgrading an existing cataloger), but a
    user is never demoted by seeding. Runs on every ``init_schema()`` so
    operators can grant access by editing env + restarting.
    """
    now = _utc_now_iso()
    for email in _split_env_csv("MARCEDIT_WEB_ADMIN_EMAILS"):
        conn.execute(
            "INSERT INTO users(email, role, status, created_at,"
            " approved_at, approved_by)"
            " VALUES (?, 'admin', 'approved', ?, ?, '__bootstrap__')"
            " ON CONFLICT(email) DO UPDATE SET"
            "   role='admin', status='approved',"
            "   approved_at=COALESCE(users.approved_at, excluded.approved_at),"
            "   approved_by=COALESCE(users.approved_by, '__bootstrap__')",
            (email, now, now),
        )
    for domain in _split_env_csv("MARCEDIT_WEB_ALLOWED_DOMAINS"):
        conn.execute(
            "INSERT OR IGNORE INTO allowed_domains(domain, added_at, added_by)"
            " VALUES (?, ?, '__bootstrap__')",
            (domain, now),
        )


def init_schema() -> None:
    """Create tables + indexes if missing. Idempotent + thread-safe.

    Safe to call from module import; subsequent calls are a no-op
    (guarded by ``_initialized`` flag under a lock). Also enables WAL
    mode, which is a per-database file setting (persists across
    connections, so we only need to set it once).

    Versioned migrations run here too: if the stored schema version
    is below ``SCHEMA_VERSION``, each pending migration step runs in
    order, and the version row advances. Migrations must be
    idempotent — partial-failure recovery just re-runs them.
    """
    global _initialized
    with _init_lock:
        if _initialized:
            return
        with connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA_SQL)
            _seed_access_control(conn)
            row = conn.execute(
                "SELECT version FROM _schema_version"
            ).fetchone()
            current_version = row["version"] if row else 0
            if current_version < 2:
                _migrate_v1_to_v2(conn)
            if current_version < 6:
                _migrate_to_v6(conn)
            # After all pending steps land, set the version row to the
            # newest. INSERT OR REPLACE keeps the table single-row.
            conn.execute("DELETE FROM _schema_version")
            conn.execute(
                "INSERT INTO _schema_version(version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
        _initialized = True


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """File → SQL migration for user tasks (TASK-050).

    Scans the legacy ``data/tasks/users/<slug>/*.py`` and
    ``data/tasks/shared/*.py`` directories and inserts one ``tasks``
    row per file. Files that fail to parse are skipped with a
    logged warning — operators can recover from the on-disk
    originals. Uses ``INSERT OR IGNORE`` so re-running this
    migration on a partially-populated table is a no-op.
    """
    # Local imports — these modules depend on db.py at top level
    # (they call ``db.connect()``), so we have to wait until function
    # call time to import them and avoid a circular import.
    from . import editor, task_storage

    now = _utc_now_iso()
    root = task_storage.tasks_root()
    if not root.exists():
        return

    users_root = root / "users"
    if users_root.is_dir():
        for user_dir in users_root.iterdir():
            if not user_dir.is_dir():
                continue
            owner = user_dir.name  # safe_user_slug already kept email shape
            for py in sorted(user_dir.glob("*.py")):
                _import_task_file(conn, py, owner, "private", now)

    shared_dir = root / "shared"
    if shared_dir.is_dir():
        for py in sorted(shared_dir.glob("*.py")):
            _import_task_file(conn, py, SHARED_OWNER_SENTINEL, "shared", now)


def _import_task_file(
    conn: sqlite3.Connection,
    py_path,
    owner: str,
    visibility: str,
    now_iso: str,
) -> None:
    """Parse one on-disk task file and insert it as a tasks row.

    Skips files the parser can't handle (logged warning) so one bad
    file doesn't abort the whole migration.
    """
    from . import editor  # local import: see _migrate_v1_to_v2

    try:
        parsed = editor.parse_user_task_file(py_path)
    except Exception as exc:  # noqa: BLE001 — migration must not crash
        logger.warning(
            "migration: skipping unparseable %s: %s", py_path, exc
        )
        return
    conn.execute(
        "INSERT OR IGNORE INTO tasks"
        "(owner_email, name, description, body, extra_imports,"
        " visibility, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            owner,
            parsed["name"],
            parsed["description"],
            parsed["body"],
            "",
            visibility,
            now_iso,
            now_iso,
        ),
    )


def _utc_now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _migrate_to_v6(conn: sqlite3.Connection) -> None:
    """Add job/project foundation and attach legacy uploads (TASK-081)."""
    upload_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(uploads)")
    }
    if "job_id" not in upload_cols:
        conn.execute("ALTER TABLE uploads ADD COLUMN job_id INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploads_job ON uploads(job_id)")

    now = _utc_now_iso()
    users = [
        row["user_email"]
        for row in conn.execute(
            "SELECT DISTINCT user_email FROM uploads WHERE user_email <> ''"
        )
    ]
    for user in users:
        job_id = _ensure_default_job(conn, user, now)
        conn.execute(
            "UPDATE uploads SET job_id = ?"
            " WHERE user_email = ? AND job_id IS NULL",
            (job_id, user),
        )


def _ensure_default_job(
    conn: sqlite3.Connection,
    owner_email: str,
    now: str,
) -> int:
    row = conn.execute(
        "SELECT id FROM jobs WHERE owner_email = ? AND name = ?",
        (owner_email, "Personal uploads"),
    ).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO jobs(owner_email, name, description, visibility,"
        " created_at, updated_at)"
        " VALUES (?, 'Personal uploads', '', 'private', ?, ?)",
        (owner_email, now, now),
    )
    job_id = int(cur.lastrowid)
    conn.execute(
        "INSERT OR IGNORE INTO job_access(job_id, user_email, role, created_at)"
        " VALUES (?, ?, 'owner', ?)",
        (job_id, owner_email, now),
    )
    return job_id


def reset_for_tests() -> None:
    """Drop the initialized flag so the next ``init_schema()`` runs.

    Tests that switch ``MARCEDIT_WEB_DB_PATH`` need this — otherwise
    a second test would short-circuit before touching the new path.
    """
    global _initialized
    with _init_lock:
        _initialized = False


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS _schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS audit_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,
    user_email   TEXT    NOT NULL,
    kind         TEXT    NOT NULL,
    payload_json TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_user_ts ON audit_events(user_email, ts);
CREATE INDEX IF NOT EXISTS idx_audit_kind_ts ON audit_events(kind, ts);

CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_email   TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    body          TEXT    NOT NULL,
    extra_imports TEXT    NOT NULL DEFAULT '',
    visibility    TEXT    NOT NULL DEFAULT 'private'
                  CHECK(visibility IN ('private','shared')),
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    UNIQUE(owner_email, name)
);

CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner_email);
CREATE INDEX IF NOT EXISTS idx_tasks_visibility ON tasks(visibility);

CREATE TABLE IF NOT EXISTS uploads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email    TEXT    NOT NULL,
    job_id        INTEGER,
    filename      TEXT    NOT NULL,
    file_path     TEXT    NOT NULL,
    record_count  INTEGER NOT NULL,
    file_bytes    INTEGER NOT NULL,
    uploaded_at   TEXT    NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_uploads_user_active ON uploads(user_email, active);

CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_email   TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    visibility    TEXT    NOT NULL DEFAULT 'private'
                  CHECK(visibility IN ('private','shared')),
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    UNIQUE(owner_email, name)
);

CREATE INDEX IF NOT EXISTS idx_jobs_owner ON jobs(owner_email);

CREATE TABLE IF NOT EXISTS job_access (
    job_id      INTEGER NOT NULL,
    user_email  TEXT    NOT NULL,
    role        TEXT    NOT NULL
                CHECK(role IN ('owner','editor','viewer')),
    created_at  TEXT    NOT NULL,
    PRIMARY KEY(job_id, user_email),
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_access_user ON job_access(user_email);

CREATE TABLE IF NOT EXISTS job_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER NOT NULL,
    user_email   TEXT    NOT NULL,
    kind         TEXT    NOT NULL,
    label        TEXT    NOT NULL,
    before_path  TEXT    NOT NULL,
    after_path   TEXT    NOT NULL,
    summary_json TEXT    NOT NULL DEFAULT '{}',
    created_at   TEXT    NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_snapshots_job_created
    ON job_snapshots(job_id, created_at);

CREATE TABLE IF NOT EXISTS job_versions (
    job_id     INTEGER PRIMARY KEY,
    version    INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT    NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS users (
    email       TEXT PRIMARY KEY,
    role        TEXT NOT NULL DEFAULT 'cataloger'
                CHECK(role IN ('admin','cataloger')),
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('approved','pending','revoked')),
    created_at  TEXT NOT NULL,
    approved_at TEXT,
    approved_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);

CREATE TABLE IF NOT EXISTS allowed_domains (
    domain   TEXT PRIMARY KEY,
    added_at TEXT NOT NULL,
    added_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS advisory_locks (
    resource_type TEXT NOT NULL,
    resource_id   TEXT NOT NULL,
    holder_email  TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY(resource_type, resource_id)
);

CREATE INDEX IF NOT EXISTS idx_advisory_locks_expires
    ON advisory_locks(expires_at);
"""
