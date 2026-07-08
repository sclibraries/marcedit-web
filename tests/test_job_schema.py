"""Schema tests for the TASK-081 job/project foundation."""

from __future__ import annotations

from marcedit_web.lib import db


def test_v6_creates_jobs_job_access_and_upload_job_id():
    """Schema v6 must carry the server-side job/project model."""
    db.init_schema()

    with db.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        upload_cols = {row["name"] for row in conn.execute("PRAGMA table_info(uploads)")}
        job_cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        access_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(job_access)")
        }

    assert {"jobs", "job_access"}.issubset(tables)
    assert "job_id" in upload_cols
    assert {"id", "owner_email", "name", "visibility"}.issubset(job_cols)
    assert {"job_id", "user_email", "role"}.issubset(access_cols)


def test_v6_migrates_existing_uploads_to_default_personal_job(tmp_path, monkeypatch):
    """Existing upload rows should gain a default job without data loss."""
    db_path = tmp_path / "legacy.db"
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(db_path))
    db.reset_for_tests()

    with db.connect() as conn:
        conn.executescript("""
        CREATE TABLE _schema_version (version INTEGER PRIMARY KEY);
        INSERT INTO _schema_version(version) VALUES (5);
        CREATE TABLE uploads (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email    TEXT    NOT NULL,
            filename      TEXT    NOT NULL,
            file_path     TEXT    NOT NULL,
            record_count  INTEGER NOT NULL,
            file_bytes    INTEGER NOT NULL,
            uploaded_at   TEXT    NOT NULL,
            active        INTEGER NOT NULL DEFAULT 1
        );
        INSERT INTO uploads(user_email, filename, file_path, record_count,
                            file_bytes, uploaded_at, active)
        VALUES ('alice@example.edu', 'legacy.mrc', '/tmp/legacy.mrc', 2,
                10, '2026-06-25T12:00:00Z', 1);
        """)

    db.reset_for_tests()
    db.init_schema()

    with db.connect() as conn:
        upload = conn.execute(
            "SELECT filename, job_id FROM uploads WHERE filename='legacy.mrc'"
        ).fetchone()
        job = conn.execute(
            "SELECT owner_email, name, visibility FROM jobs WHERE id=?",
            (upload["job_id"],),
        ).fetchone()
        version = conn.execute("SELECT version FROM _schema_version").fetchone()

    assert upload["job_id"] is not None
    assert job["owner_email"] == "alice@example.edu"
    assert job["name"] == "Personal uploads"
    assert job["visibility"] == "private"
    assert version["version"] == db.SCHEMA_VERSION


def test_v9_adds_job_workflow_columns_notes_and_activity():
    """TASK-118 needs status, review notes, and activity for shared review."""
    db.init_schema()

    with db.connect() as conn:
        job_cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        note_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(job_review_notes)")
        }
        activity_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(job_activity)")
        }

    assert {"status", "archived_at", "archived_by"}.issubset(job_cols)
    assert {
        "id",
        "job_id",
        "anchor_kind",
        "anchor_value",
        "note",
        "author_email",
        "category",
        "resolved",
        "created_at",
        "resolved_at",
        "resolved_by",
    }.issubset(note_cols)
    assert {
        "id",
        "job_id",
        "kind",
        "message",
        "actor_email",
        "created_at",
    }.issubset(activity_cols)
