"""Conservative legacy-upload migration into job file work items (TASK-151)."""

from __future__ import annotations

from pathlib import Path

from marcedit_web.lib import db, job_files, provenance


OWNER = "owner@example.edu"


def _seed_v11_job(tmp_path: Path) -> int:
    """Create the real schema shape immediately before the v12 migration."""
    with db.connect() as conn:
        conn.executescript(db._SCHEMA_SQL)  # noqa: SLF001 - migration fixture
        db._migrate_to_v9(conn)  # noqa: SLF001 - migration fixture
        db._migrate_to_v10(conn)  # noqa: SLF001 - migration fixture
        db._migrate_to_v11(conn)  # noqa: SLF001 - migration fixture
        conn.execute("INSERT INTO _schema_version(version) VALUES (11)")
        job_id = int(
            conn.execute(
                "INSERT INTO jobs(owner_email,name,created_at,updated_at)"
                " VALUES(?,?,?,?) RETURNING id",
                (
                    OWNER,
                    "Legacy Routledge",
                    "2026-07-01T12:00:00Z",
                    "2026-07-01T12:00:00Z",
                ),
            ).fetchone()["id"]
        )
        conn.execute(
            "INSERT INTO job_access(job_id,user_email,role,created_at)"
            " VALUES(?,?,?,?)",
            (job_id, OWNER, "owner", "2026-07-01T12:00:00Z"),
        )
    return job_id


def _seed_upload(
    job_id: int | None,
    path: Path,
    *,
    filename: str,
    removed_at: str | None = None,
) -> int:
    with db.connect() as conn:
        return int(
            conn.execute(
                "INSERT INTO uploads(user_email,job_id,filename,file_path,record_count,"
                "file_bytes,uploaded_at,active,removed_at) VALUES(?,?,?,?,?,?,?,?,?)"
                " RETURNING id",
                (
                    OWNER,
                    job_id,
                    filename,
                    str(path),
                    3,
                    path.stat().st_size if path.exists() else 6,
                    "2026-07-02T09:30:00Z",
                    1,
                    removed_at,
                ),
            ).fetchone()["id"]
        )


def _migrated_file(upload_id: int):
    with db.connect() as conn:
        return conn.execute(
            "SELECT job_files.id AS job_file_id,job_files.current_version_id,"
            "job_files.created_by,job_files.created_at,job_file_versions.*"
            " FROM job_files JOIN job_file_versions"
            " ON job_file_versions.job_file_id=job_files.id"
            " WHERE job_files.original_upload_id=?",
            (upload_id,),
        ).fetchone()


def test_existing_upload_migrates_once_to_immutable_version(tmp_path, monkeypatch):
    """A legacy path becomes copied v1 evidence, never a mutable alias."""
    root = tmp_path / "job-files"
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(root))
    job_id = _seed_v11_job(tmp_path)
    original = tmp_path / "legacy.mrc"
    original.write_bytes(b"legacy")
    upload_id = _seed_upload(job_id, original, filename="legacy.mrc")

    db.reset_for_tests()
    db.init_schema()
    first = _migrated_file(upload_id)

    assert first is not None
    assert first["version_number"] == 1
    assert first["source_kind"] == "legacy-upload"
    assert first["created_by"] == OWNER
    assert first["created_at"] == "2026-07-02T09:30:00Z"
    assert Path(first["file_path"]).read_bytes() == b"legacy"
    assert Path(first["file_path"]) != original
    assert Path(first["file_path"]).name == "v000001.mrc"
    assert first["current_version_id"] == first["id"]

    db.reset_for_tests()
    db.init_schema()
    with db.connect() as conn:
        ids = conn.execute(
            "SELECT id FROM job_files WHERE original_upload_id=?",
            (upload_id,),
        ).fetchall()
        versions = conn.execute(
            "SELECT id FROM job_file_versions WHERE job_file_id=?",
            (first["job_file_id"],),
        ).fetchall()
    assert [row["id"] for row in ids] == [first["job_file_id"]]
    assert [row["id"] for row in versions] == [first["id"]]


def test_missing_upload_warns_without_blocking_other_eligible_uploads(
    tmp_path, monkeypatch, caplog,
):
    """One missing legacy artifact must not create a row or abort migration."""
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files"))
    job_id = _seed_v11_job(tmp_path)
    missing = tmp_path / "missing.mrc"
    missing_id = _seed_upload(job_id, missing, filename="missing.mrc")
    readable = tmp_path / "readable.mrc"
    readable.write_bytes(b"readable")
    readable_id = _seed_upload(job_id, readable, filename="readable.mrc")

    db.reset_for_tests()
    db.init_schema()

    assert _migrated_file(missing_id) is None
    assert Path(_migrated_file(readable_id)["file_path"]).read_bytes() == b"readable"
    assert str(missing_id) in caplog.text
    assert str(missing) in caplog.text


def test_copy_failure_leaves_no_partial_row_and_migration_continues(
    tmp_path, monkeypatch, caplog,
):
    """Per-upload disk failures are isolated from later legacy uploads."""
    root = tmp_path / "job-files"
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(root))
    job_id = _seed_v11_job(tmp_path)
    broken = tmp_path / "broken.mrc"
    broken.write_bytes(b"broken")
    broken_id = _seed_upload(job_id, broken, filename="broken.mrc")
    readable = tmp_path / "later.mrc"
    readable.write_bytes(b"later")
    readable_id = _seed_upload(job_id, readable, filename="later.mrc")
    real_copy = job_files.shutil.copyfile

    def fail_one_copy(source, target):
        if Path(source) == broken:
            Path(target).write_bytes(b"partial")
            raise OSError("disk full")
        return real_copy(source, target)

    monkeypatch.setattr(job_files.shutil, "copyfile", fail_one_copy)

    db.reset_for_tests()
    db.init_schema()

    assert _migrated_file(broken_id) is None
    assert Path(_migrated_file(readable_id)["file_path"]).read_bytes() == b"later"
    assert str(broken_id) in caplog.text
    assert str(broken) in caplog.text
    assert list((root / "pending").iterdir()) == []


def test_removed_or_unassigned_uploads_remain_legacy_only(tmp_path, monkeypatch):
    """Only non-removed uploads with an explicit job relationship are eligible."""
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files"))
    job_id = _seed_v11_job(tmp_path)
    removed = tmp_path / "removed.mrc"
    removed.write_bytes(b"removed")
    removed_id = _seed_upload(
        job_id,
        removed,
        filename="removed.mrc",
        removed_at="2026-07-03T10:00:00Z",
    )
    unassigned = tmp_path / "unassigned.mrc"
    unassigned.write_bytes(b"unassigned")
    unassigned_id = _seed_upload(None, unassigned, filename="unassigned.mrc")

    db.reset_for_tests()
    db.init_schema()

    assert _migrated_file(removed_id) is None
    assert _migrated_file(unassigned_id) is None


def test_ambiguous_snapshot_remains_unlinked_legacy_job_history(tmp_path, monkeypatch):
    """A job id shared by uploads and a snapshot is not evidence of ownership."""
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(tmp_path / "job-files"))
    job_id = _seed_v11_job(tmp_path)
    for name in ("first.mrc", "second.mrc"):
        source = tmp_path / name
        source.write_bytes(name.encode())
        _seed_upload(job_id, source, filename=name)
    with db.connect() as conn:
        snapshot_id = int(
            conn.execute(
                "INSERT INTO job_snapshots(job_id,user_email,kind,label,before_path,"
                "after_path,created_at) VALUES(?,?,?,?,?,?,?) RETURNING id",
                (
                    job_id,
                    OWNER,
                    "quick-batch",
                    "Ambiguous legacy history",
                    str(tmp_path / "before.mrc"),
                    str(tmp_path / "after.mrc"),
                    "2026-07-04T10:00:00Z",
                ),
            ).fetchone()["id"]
        )

    db.reset_for_tests()
    db.init_schema()

    snapshots = provenance.list_snapshots(job_id)
    with db.connect() as conn:
        snapshot_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(job_snapshots)")
        }
        migrated_files = conn.execute(
            "SELECT original_upload_id FROM job_files WHERE job_id=? ORDER BY id",
            (job_id,),
        ).fetchall()
    assert snapshots[0]["id"] == snapshot_id
    assert snapshots[0]["label"] == "Ambiguous legacy history"
    assert {"job_file_id", "job_file_version_id"}.isdisjoint(snapshot_columns)
    assert len(migrated_files) == 2
