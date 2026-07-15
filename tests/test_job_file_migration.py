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
            "job_files.display_name,job_files.created_by,job_files.created_at,"
            "job_file_versions.*"
            " FROM job_files JOIN job_file_versions"
            " ON job_file_versions.job_file_id=job_files.id"
            " WHERE job_files.original_upload_id=?",
            (upload_id,),
        ).fetchone()


def _create_empty_v12_tables() -> None:
    with db.connect() as conn:
        db._migrate_to_v12(conn)  # noqa: SLF001 - partial-migration fixture


def _seed_partial_job_file(job_id: int, upload_id: int) -> int:
    with db.connect() as conn:
        return int(
            conn.execute(
                "INSERT INTO job_files(job_id,original_upload_id,display_name,"
                "created_by,created_at,updated_by,updated_at)"
                " VALUES(?,?,?,?,?,?,?) RETURNING id",
                (
                    job_id,
                    upload_id,
                    "legacy.mrc",
                    OWNER,
                    "2026-07-02T09:30:00Z",
                    OWNER,
                    "2026-07-02T09:30:00Z",
                ),
            ).fetchone()["id"]
        )


def _seed_partial_v1(file_id: int, path: Path) -> int:
    with db.connect() as conn:
        return int(
            conn.execute(
                "INSERT INTO job_file_versions(job_file_id,version_number,file_path,"
                "record_count,file_bytes,source_kind,label,created_by,created_at)"
                " VALUES(?,1,?,?,?,?,?,?,?) RETURNING id",
                (
                    file_id,
                    str(path),
                    3,
                    6,
                    "legacy-upload",
                    "legacy.mrc",
                    OWNER,
                    "2026-07-02T09:30:00Z",
                ),
            ).fetchone()["id"]
        )


def _assert_single_complete_migration(upload_id: int, expected: bytes) -> None:
    migrated = _migrated_file(upload_id)
    assert migrated is not None
    assert migrated["current_version_id"] == migrated["id"]
    assert Path(migrated["file_path"]).read_bytes() == expected
    with db.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM job_files WHERE original_upload_id=?",
            (upload_id,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM job_file_versions WHERE job_file_id=?",
            (migrated["job_file_id"],),
        ).fetchone()[0] == 1


def test_existing_upload_migrates_once_to_immutable_version(tmp_path, monkeypatch):
    """A legacy path becomes copied v1 evidence, never a mutable alias."""
    root = tmp_path / "job-files"
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(root))
    job_id = _seed_v11_job(tmp_path)
    original = tmp_path / "legacy.mrc"
    original.write_bytes(b"legacy")
    upload_id = _seed_upload(job_id, original, filename="legacy.mrc")
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET active=0,status='archived',archived_at=?,archived_by=?"
            " WHERE id=?",
            ("2026-07-05T10:00:00Z", OWNER, job_id),
        )
        conn.execute(
            "INSERT INTO job_review_notes(job_id,anchor_kind,note,author_email,"
            "created_at) VALUES(?,?,?,?,?)",
            (
                job_id,
                "job",
                "Preserve this legacy note.",
                OWNER,
                "2026-07-05T09:00:00Z",
            ),
        )
        job_before = dict(conn.execute(
            "SELECT active,status,archived_at,archived_by FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone())
        access_before = [dict(row) for row in conn.execute(
            "SELECT user_email,role,created_at FROM job_access WHERE job_id=?",
            (job_id,),
        )]
        notes_before = [dict(row) for row in conn.execute(
            "SELECT anchor_kind,note,author_email,created_at"
            " FROM job_review_notes WHERE job_id=?",
            (job_id,),
        )]

    db.reset_for_tests()
    db.init_schema()
    first = _migrated_file(upload_id)

    assert first is not None
    assert first["version_number"] == 1
    assert first["source_kind"] == "legacy-upload"
    assert first["display_name"] == "legacy.mrc"
    assert first["record_count"] == 3
    assert first["file_bytes"] == 6
    assert first["created_by"] == OWNER
    assert first["created_at"] == "2026-07-02T09:30:00Z"
    assert Path(first["file_path"]).read_bytes() == b"legacy"
    assert Path(first["file_path"]) != original
    assert Path(first["file_path"]).name == "v000001.mrc"
    assert first["current_version_id"] == first["id"]

    original.unlink()
    with db.connect() as conn:
        job_files._migrate_uploads_to_job_files(conn)  # noqa: SLF001
    with db.connect() as conn:
        ids = conn.execute(
            "SELECT id FROM job_files WHERE original_upload_id=?",
            (upload_id,),
        ).fetchall()
        versions = conn.execute(
            "SELECT id FROM job_file_versions WHERE job_file_id=?",
            (first["job_file_id"],),
        ).fetchall()
        job_after = dict(conn.execute(
            "SELECT active,status,archived_at,archived_by FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone())
        access_after = [dict(row) for row in conn.execute(
            "SELECT user_email,role,created_at FROM job_access WHERE job_id=?",
            (job_id,),
        )]
        notes_after = [dict(row) for row in conn.execute(
            "SELECT anchor_kind,note,author_email,created_at"
            " FROM job_review_notes WHERE job_id=?",
            (job_id,),
        )]
    assert [row["id"] for row in ids] == [first["job_file_id"]]
    assert [row["id"] for row in versions] == [first["id"]]
    assert job_after == job_before
    assert access_after == access_before
    assert notes_after == notes_before


def test_partial_job_file_without_version_rebuilds_same_file_on_restart(
    tmp_path, monkeypatch,
):
    """A committed file row alone is not a completed upload migration."""
    root = tmp_path / "job-files"
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(root))
    job_id = _seed_v11_job(tmp_path)
    _create_empty_v12_tables()
    source = tmp_path / "legacy.mrc"
    source.write_bytes(b"legacy")
    upload_id = _seed_upload(job_id, source, filename="legacy.mrc")
    file_id = _seed_partial_job_file(job_id, upload_id)
    partial_target = root / str(file_id) / "versions" / "v000001.mrc"
    partial_target.parent.mkdir(parents=True)
    partial_target.write_bytes(b"unreferenced-partial")

    db.reset_for_tests()
    db.init_schema()

    _assert_single_complete_migration(upload_id, b"legacy")
    assert _migrated_file(upload_id)["job_file_id"] == file_id


def test_partial_current_pointer_reuses_existing_v1_on_helper_rerun(
    tmp_path, monkeypatch,
):
    """A durable v1 with a missing current pointer needs SQL reconciliation."""
    root = tmp_path / "job-files"
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(root))
    job_id = _seed_v11_job(tmp_path)
    _create_empty_v12_tables()
    source = tmp_path / "legacy.mrc"
    source.write_bytes(b"legacy")
    upload_id = _seed_upload(job_id, source, filename="legacy.mrc")
    file_id = _seed_partial_job_file(job_id, upload_id)
    target = root / str(file_id) / "versions" / "v000001.mrc"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing-v1")
    version_id = _seed_partial_v1(file_id, target)

    with db.connect() as conn:
        job_files._migrate_uploads_to_job_files(conn)  # noqa: SLF001
        job_files._migrate_uploads_to_job_files(conn)  # noqa: SLF001

    _assert_single_complete_migration(upload_id, b"existing-v1")
    assert _migrated_file(upload_id)["id"] == version_id


def test_partial_missing_immutable_v1_rebuilds_bytes_without_duplicates(
    tmp_path, monkeypatch,
):
    """A current v1 row is incomplete while its immutable artifact is absent."""
    root = tmp_path / "job-files"
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(root))
    job_id = _seed_v11_job(tmp_path)
    _create_empty_v12_tables()
    source = tmp_path / "legacy.mrc"
    source.write_bytes(b"legacy")
    upload_id = _seed_upload(job_id, source, filename="legacy.mrc")
    file_id = _seed_partial_job_file(job_id, upload_id)
    target = root / str(file_id) / "versions" / "v000001.mrc"
    version_id = _seed_partial_v1(file_id, target)
    with db.connect() as conn:
        conn.execute(
            "UPDATE job_files SET current_version_id=? WHERE id=?",
            (version_id, file_id),
        )

    with db.connect() as conn:
        job_files._migrate_uploads_to_job_files(conn)  # noqa: SLF001
        job_files._migrate_uploads_to_job_files(conn)  # noqa: SLF001

    _assert_single_complete_migration(upload_id, b"legacy")
    assert _migrated_file(upload_id)["id"] == version_id


def test_partial_rebuild_never_overwrites_a_referenced_version_path(
    tmp_path, monkeypatch, caplog,
):
    """Cleanup may own an orphan partial path, never another version's bytes."""
    root = tmp_path / "job-files"
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(root))
    job_id = _seed_v11_job(tmp_path)
    _create_empty_v12_tables()
    source = tmp_path / "legacy.mrc"
    source.write_bytes(b"legacy")
    upload_id = _seed_upload(job_id, source, filename="legacy.mrc")
    partial_file_id = _seed_partial_job_file(job_id, upload_id)
    referenced_path = (
        root / str(partial_file_id) / "versions" / "v000001.mrc"
    )
    referenced_path.parent.mkdir(parents=True)
    referenced_path.write_bytes(b"other-immutable-version")
    with db.connect() as conn:
        other_file_id = int(conn.execute(
            "INSERT INTO job_files(job_id,display_name,created_by,created_at,"
            "updated_by,updated_at) VALUES(?,?,?,?,?,?) RETURNING id",
            (
                job_id,
                "other.mrc",
                OWNER,
                "2026-07-02T09:30:00Z",
                OWNER,
                "2026-07-02T09:30:00Z",
            ),
        ).fetchone()["id"])
        other_version_id = int(conn.execute(
            "INSERT INTO job_file_versions(job_file_id,version_number,file_path,"
            "record_count,file_bytes,source_kind,created_by,created_at)"
            " VALUES(?,1,?,?,?,?,?,?) RETURNING id",
            (
                other_file_id,
                str(referenced_path),
                3,
                len(b"other-immutable-version"),
                "original",
                OWNER,
                "2026-07-02T09:30:00Z",
            ),
        ).fetchone()["id"])
        conn.execute(
            "UPDATE job_files SET current_version_id=? WHERE id=?",
            (other_version_id, other_file_id),
        )

    with db.connect() as conn:
        job_files._migrate_uploads_to_job_files(conn)  # noqa: SLF001

    assert referenced_path.read_bytes() == b"other-immutable-version"
    assert _migrated_file(upload_id) is None
    assert str(upload_id) in caplog.text


def test_failed_pointer_repair_preserves_newly_rebuilt_referenced_bytes(
    tmp_path, monkeypatch, caplog,
):
    """Rollback cleanup must recheck SQL ownership before unlinking a target."""
    root = tmp_path / "job-files"
    monkeypatch.setenv("MARCEDIT_WEB_JOB_FILES_ROOT", str(root))
    job_id = _seed_v11_job(tmp_path)
    _create_empty_v12_tables()
    source = tmp_path / "legacy.mrc"
    source.write_bytes(b"legacy")
    upload_id = _seed_upload(job_id, source, filename="legacy.mrc")
    file_id = _seed_partial_job_file(job_id, upload_id)
    target = root / str(file_id) / "versions" / "v000001.mrc"
    _seed_partial_v1(file_id, target)
    with db.connect() as conn:
        conn.execute("""
            CREATE TRIGGER reject_migration_pointer
            BEFORE UPDATE OF current_version_id ON job_files
            BEGIN
                SELECT RAISE(FAIL, 'pointer rejected');
            END
        """)

    with db.connect() as conn:
        job_files._migrate_uploads_to_job_files(conn)  # noqa: SLF001

    assert target.read_bytes() == b"legacy"
    assert str(upload_id) in caplog.text
    with db.connect() as conn:
        conn.execute("DROP TRIGGER reject_migration_pointer")
        job_files._migrate_uploads_to_job_files(conn)  # noqa: SLF001

    _assert_single_complete_migration(upload_id, b"legacy")


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
