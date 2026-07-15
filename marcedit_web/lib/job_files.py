"""Durable per-file work items and immutable MARC versions (TASK-151)."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from . import db, jobs
from .record_store import RecordStore


class JobFileError(ValueError):
    """Raised when a job-file operation is invalid."""


def versions_root() -> Path:
    return Path(os.environ.get("MARCEDIT_WEB_JOB_FILES_ROOT", "data/job-files"))


def attach_file(
    *,
    job_id: int,
    user_email: str,
    source_path: Path,
    filename: str,
    record_count: int,
    file_bytes: int,
    upload_id: int | None = None,
    description: str = "",
) -> dict[str, Any]:
    jobs.require_role(job_id, user_email, {"owner", "editor"})
    clean_filename = filename.strip()
    if not clean_filename or not source_path.is_file():
        raise JobFileError("a readable MARC file and filename are required")
    if file_bytes != source_path.stat().st_size:
        raise JobFileError("file size does not match the persisted MARC file")

    now = _utc_now_iso()
    candidate = versions_root() / "pending" / f"{uuid.uuid4().hex}.mrc"
    try:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, candidate)
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "INSERT INTO job_files(job_id,original_upload_id,display_name,description,"
                "created_by,created_at,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    upload_id,
                    clean_filename,
                    description.strip(),
                    user_email,
                    now,
                    user_email,
                    now,
                ),
            )
            file_id = int(cursor.lastrowid)
            target = versions_root() / str(file_id) / "versions" / "v000001.mrc"
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(candidate, target)
            version = conn.execute(
                "INSERT INTO job_file_versions(job_file_id,version_number,file_path,"
                "record_count,file_bytes,source_kind,label,created_by,created_at) "
                "VALUES(?,1,?,?,?,?,?,?,?) RETURNING id",
                (
                    file_id,
                    str(target),
                    record_count,
                    file_bytes,
                    "original",
                    clean_filename,
                    user_email,
                    now,
                ),
            ).fetchone()
            conn.execute(
                "UPDATE job_files SET current_version_id=? WHERE id=?",
                (version["id"], file_id),
            )
    except Exception:
        candidate.unlink(missing_ok=True)
        if "target" in locals():
            target.unlink(missing_ok=True)
        raise
    return get_file(file_id, user_email)


def list_files(
    job_id: int,
    user_email: str,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    db.init_schema()
    archived_clause = "" if include_archived else " AND job_files.archived_at IS NULL"
    with db.connect() as conn:
        rows = conn.execute(
            _FILE_SELECT
            + " WHERE job_files.job_id=? AND job_access.user_email=?"
            + archived_clause
            + " ORDER BY job_files.id",
            (job_id, user_email.strip().lower()),
        ).fetchall()
    return [_dict(row) for row in rows]


def get_file(file_id: int, user_email: str) -> dict[str, Any]:
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            _FILE_SELECT + " WHERE job_files.id=? AND job_access.user_email=?",
            (file_id, user_email.strip().lower()),
        ).fetchone()
    if row is None:
        raise JobFileError("job file not found")
    return _dict(row)


def get_current_version(file_id: int, user_email: str) -> dict[str, Any]:
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            _VERSION_SELECT
            + " WHERE job_files.id=? AND job_file_versions.id=job_files.current_version_id"
            + " AND job_access.user_email=?",
            (file_id, user_email.strip().lower()),
        ).fetchone()
    if row is None:
        raise JobFileError("job file version not found")
    return _dict(row)


def get_version(version_id: int, user_email: str) -> dict[str, Any]:
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            _VERSION_SELECT
            + " WHERE job_file_versions.id=? AND job_access.user_email=?",
            (version_id, user_email.strip().lower()),
        ).fetchone()
    if row is None:
        raise JobFileError("job file version not found")
    return _dict(row)


def list_versions(file_id: int, user_email: str) -> list[dict[str, Any]]:
    """List one accessible file's immutable versions, oldest first."""
    db.init_schema()
    with db.connect() as conn:
        rows = conn.execute(
            _VERSION_SELECT
            + " WHERE job_files.id=? AND job_access.user_email=?"
            + " ORDER BY job_file_versions.version_number",
            (file_id, user_email.strip().lower()),
        ).fetchall()
    return [_dict(row) for row in rows]


def create_export(
    *,
    file_id: int,
    opened_version_id: int,
    user_email: str,
    purpose: str,
    description: str = "",
    filename: str | None = None,
) -> dict[str, Any]:
    """Retain a labeled copy of the exact checked-out current version."""
    clean_purpose = purpose.strip()
    if not clean_purpose:
        raise JobFileError("an export purpose is required")

    db.init_schema()
    target: Path | None = None
    export_id: int | None = None
    try:
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = _transition_row(conn, file_id, user_email)
            _assert_transition_checkout(
                conn,
                file_id,
                user_email,
                opened_version_id,
            )
            version = conn.execute(
                "SELECT id,file_path,record_count,file_bytes,validation_json,"
                "approval_kind FROM job_file_versions"
                " WHERE id=? AND job_file_id=?",
                (opened_version_id, file_id),
            ).fetchone()
            if version is None:
                raise JobFileError("job file version not found")

            clean_filename = _safe_export_filename(
                filename or str(row["display_name"])
            )
            target = _copy_export_exclusive(
                Path(version["file_path"]),
                versions_root() / str(file_id) / "exports",
                clean_filename,
            )
            if target.stat().st_size != int(version["file_bytes"]):
                raise JobFileError("export size does not match its source version")
            copied = RecordStore.from_path(target)
            if (
                copied.count() != int(version["record_count"])
                or copied.malformed_count() != 0
            ):
                raise JobFileError("export record count does not match its source version")

            row = _transition_row(conn, file_id, user_email)
            _assert_transition_checkout(
                conn,
                file_id,
                user_email,
                opened_version_id,
            )
            version = conn.execute(
                "SELECT id,file_path,record_count,file_bytes,validation_json,"
                "approval_kind FROM job_file_versions"
                " WHERE id=? AND job_file_id=?",
                (opened_version_id, file_id),
            ).fetchone()
            if version is None:
                raise JobFileError("job file version not found")

            now = _utc_now_iso()
            state = "ready" if version["approval_kind"] is not None else "draft"
            export_id = int(conn.execute(
                "INSERT INTO job_file_exports(job_file_id,version_id,purpose,"
                "description,filename,file_path,record_count,validation_json,state,"
                "created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (
                    file_id,
                    opened_version_id,
                    clean_purpose,
                    description.strip(),
                    clean_filename,
                    str(target),
                    int(version["record_count"]),
                    version["validation_json"],
                    state,
                    user_email,
                    now,
                ),
            ).fetchone()["id"])
            if state == "ready":
                conn.execute(
                    "UPDATE job_files SET status='exported',updated_by=?,updated_at=?"
                    " WHERE id=?",
                    (user_email, now, file_id),
                )
            jobs._record_activity(  # noqa: SLF001 - shared transaction helper
                conn,
                int(row["job_id"]),
                "job-file-export-created",
                f"Created {state} export for {row['display_name']}: {clean_purpose}",
                user_email,
                now,
                job_file_id=file_id,
            )
    except Exception as exc:
        if target is not None and target.exists():
            try:
                referenced_export_id = _export_reference_id_for_path(target)
            except Exception as verification_exc:
                raise JobFileError(
                    "export creation could not be confirmed; retained export bytes"
                ) from verification_exc
            if referenced_export_id is not None:
                raise JobFileError(
                    "export was created, but transaction confirmation failed"
                ) from exc
            target.unlink(missing_ok=True)
        raise
    return get_export(export_id, user_email)


def get_export(export_id: int, user_email: str) -> dict[str, Any]:
    """Return one retained export visible through its parent job."""
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            _EXPORT_SELECT
            + " WHERE job_file_exports.id=? AND job_access.user_email=?",
            (export_id, user_email.strip().lower()),
        ).fetchone()
    if row is None:
        raise JobFileError("job file export not found")
    return _dict(row)


def list_exports(file_id: int, user_email: str) -> list[dict[str, Any]]:
    """List retained exports for one accessible file, newest first."""
    db.init_schema()
    with db.connect() as conn:
        rows = conn.execute(
            _EXPORT_SELECT
            + " WHERE job_file_exports.job_file_id=?"
            " AND job_access.user_email=?"
            " ORDER BY job_file_exports.created_at DESC,job_file_exports.id DESC",
            (file_id, user_email.strip().lower()),
        ).fetchall()
    return [_dict(row) for row in rows]


def mark_export_loaded(
    export_id: int,
    *,
    by: str,
    destination: str,
    external_id: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Record a manual downstream load without changing or deleting its file."""
    clean_destination = destination.strip()
    if not clean_destination:
        raise JobFileError("a loaded destination is required")
    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            _EXPORT_SELECT
            + " WHERE job_file_exports.id=? AND job_access.user_email=?",
            (export_id, by.strip().lower()),
        ).fetchone()
        if row is None:
            raise JobFileError("job file export not found")
        if row["access_role"] not in {"owner", "editor"}:
            raise JobFileError("owner or editor access required")
        if row["state"] != "ready":
            raise JobFileError("only a ready export can be marked loaded")
        conn.execute(
            "UPDATE job_file_exports SET state='loaded',loaded_destination=?,"
            "loaded_external_id=?,loaded_note=?,loaded_by=?,loaded_at=? WHERE id=?",
            (
                clean_destination,
                external_id.strip(),
                note.strip(),
                by,
                now,
                export_id,
            ),
        )
        jobs._record_activity(  # noqa: SLF001 - shared transaction helper
            conn,
            int(row["job_id"]),
            "job-file-export-loaded",
            f"Marked {row['display_name']} export loaded to {clean_destination}: "
            f"{row['purpose']}",
            by,
            now,
            job_file_id=int(row["job_file_id"]),
        )
    return get_export(export_id, by)


def return_for_review(
    file_id: int,
    by: str,
    *,
    opened_version_id: int,
) -> dict[str, Any]:
    """Return the exact checked-out version for review."""
    from . import collaboration

    try:
        collaboration.return_file_for_review(
            file_id,
            by,
            opened_version_id,
        )
    except collaboration.CollaborationError as exc:
        raise JobFileError(str(exc)) from exc
    return _get_file_with_current_version(file_id, by)


def request_changes(
    file_id: int,
    by: str,
    note: str,
    *,
    opened_version_id: int,
) -> dict[str, Any]:
    """Request changes to the exact checked-out version with a required note."""
    clean_note = note.strip()
    if not clean_note:
        raise JobFileError("a change-request note is required")
    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _transition_row(conn, file_id, by)
        _assert_transition_checkout(
            conn,
            file_id,
            by,
            opened_version_id,
        )
        if row["status"] != "needs_review":
            raise JobFileError(
                "changes can only be requested when a file needs review"
            )
        conn.execute(
            "INSERT INTO job_review_notes"
            "(job_id,anchor_kind,anchor_value,note,author_email,category,"
            "created_at,job_file_id,job_file_version_id)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (
                row["job_id"],
                "job_file",
                "",
                clean_note,
                by,
                "changes_requested",
                now,
                file_id,
                opened_version_id,
            ),
        )
        _set_status_and_record_activity(
            conn,
            row,
            "changes_requested",
            by,
            now,
            f"{row['display_name']} changes requested: {clean_note}",
        )
        conn.execute(
            "DELETE FROM advisory_locks"
            " WHERE resource_type='job-file' AND resource_id=?"
            " AND holder_email=?",
            (str(file_id), by),
        )
    return _get_file_with_current_version(file_id, by)


def approve_current(
    file_id: int,
    by: str,
    *,
    opened_version_id: int,
) -> dict[str, Any]:
    """Approve the exact checked-out current version as self or peer review."""
    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _transition_row(conn, file_id, by)
        _assert_transition_checkout(
            conn,
            file_id,
            by,
            opened_version_id,
        )
        current = conn.execute(
            "SELECT id,created_by,approval_kind FROM job_file_versions"
            " WHERE id=? AND job_file_id=?",
            (opened_version_id, file_id),
        ).fetchone()
        if current is None:
            raise JobFileError("job file version not found")
        if current["approval_kind"] is not None:
            raise JobFileError("this file version is already approved")
        approval_kind = (
            "self-approved" if current["created_by"] == by else "peer-approved"
        )
        conn.execute(
            "UPDATE job_file_versions SET approval_kind=?,approved_by=?,"
            "approved_at=? WHERE id=?",
            (approval_kind, by, now, opened_version_id),
        )
        _set_status_and_record_activity(
            conn,
            row,
            "approved",
            by,
            now,
            f"{row['display_name']} {approval_kind} at version "
            f"{row['current_version_number']}",
        )
    return _get_file_with_current_version(file_id, by)


def set_complete(
    file_id: int,
    by: str,
    *,
    opened_version_id: int,
) -> dict[str, Any]:
    """Explicitly complete an approved or exported exact current version."""
    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _transition_row(conn, file_id, by)
        _assert_transition_checkout(
            conn,
            file_id,
            by,
            opened_version_id,
        )
        if row["status"] not in {"approved", "exported"}:
            raise JobFileError("only approved or exported files can be completed")
        _set_status_and_record_activity(
            conn,
            row,
            "complete",
            by,
            now,
            f"Completed {row['display_name']}",
        )
    return _get_file_with_current_version(file_id, by)


def adopt_candidate(
    *,
    file_id: int,
    opened_version_id: int,
    user_email: str,
    candidate_path: Path,
    source_kind: str,
    label: str,
    summary: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically adopt owned MARC bytes as a new immutable current version."""
    from . import collaboration

    owned_candidate = Path(candidate_path)
    staged_candidate = versions_root() / "pending" / f"{uuid.uuid4().hex}.mrc"
    target: Path | None = None
    version_id: int | None = None
    renamed = False
    try:
        try:
            store = RecordStore.from_path(owned_candidate)
        except (OSError, ValueError) as exc:
            raise JobFileError("candidate is not a readable MARC file") from exc
        count = store.count()
        byte_count = owned_candidate.stat().st_size
        if count == 0:
            raise JobFileError("candidate contains no MARC records")
        if (
            store.malformed_count() > 0
            or sum(1 for _record in store.iter_records()) != count
        ):
            raise JobFileError("candidate contains malformed MARC records")

        staged_candidate.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(owned_candidate, staged_candidate)
        owned_candidate.unlink()

        db.init_schema()
        now = _utc_now_iso()
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                access = conn.execute(
                    "SELECT job_access.role,job_files.archived_at,"
                    "job_files.job_id,job_files.display_name FROM job_files"
                    " LEFT JOIN job_access ON job_access.job_id=job_files.job_id"
                    " AND job_access.user_email=? WHERE job_files.id=?",
                    (user_email.strip().lower(), file_id),
                ).fetchone()
                if access is None or access["role"] not in {"owner", "editor"}:
                    raise JobFileError("owner or editor access required")
                if access["archived_at"] is not None:
                    raise JobFileError("archived files cannot be changed")
                try:
                    collaboration._assert_file_checkout_in_tx(
                        conn,
                        file_id,
                        user_email,
                        opened_version_id,
                    )
                except collaboration.CollaborationError as exc:
                    raise JobFileError(str(exc)) from exc
                next_number = int(conn.execute(
                    "SELECT COALESCE(MAX(version_number),0)+1 AS n"
                    " FROM job_file_versions WHERE job_file_id=?",
                    (file_id,),
                ).fetchone()["n"])
                target = _version_path(file_id, next_number)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged_candidate, target)
                renamed = True
                version_id = int(conn.execute(
                    "INSERT INTO job_file_versions(job_file_id,version_number,"
                    "parent_version_id,file_path,record_count,file_bytes,source_kind,"
                    "label,summary_json,validation_json,created_by,created_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                    (
                        file_id,
                        next_number,
                        opened_version_id,
                        str(target),
                        count,
                        byte_count,
                        source_kind,
                        label,
                        json.dumps(summary or {}),
                        json.dumps(validation or {}),
                        user_email,
                        now,
                    ),
                ).fetchone()["id"])
                changed = conn.execute(
                    "UPDATE job_files SET current_version_id=?,status='in_progress',"
                    "updated_by=?,updated_at=? WHERE id=? AND current_version_id=?",
                    (version_id, user_email, now, file_id, opened_version_id),
                ).rowcount
                if changed != 1:
                    raise JobFileError("file changed since this version was opened")
                _invalidate_approval_and_supersede_exports_in_tx(
                    conn,
                    file_id,
                    version_id,
                    now,
                )
                jobs._record_activity(  # noqa: SLF001 - shared transaction helper
                    conn,
                    int(access["job_id"]),
                    "job-file-version-adopted",
                    f"Adopted {access['display_name']} v{next_number} via "
                    f"{source_kind}: {label or '(no label)'}",
                    user_email,
                    now,
                    job_file_id=file_id,
                )
            except Exception:
                if renamed and target is not None and target.exists():
                    os.replace(target, staged_candidate)
                    renamed = False
                raise
    except Exception as exc:
        if renamed and target is not None and version_id is not None:
            try:
                committed = _adoption_version_exists_in_db(
                    file_id,
                    version_id,
                    target,
                )
            except Exception as verification_exc:
                owned_candidate.unlink(missing_ok=True)
                staged_candidate.unlink(missing_ok=True)
                raise JobFileError(
                    "file version adoption could not be confirmed;"
                    " retained target bytes"
                ) from verification_exc
            if committed:
                owned_candidate.unlink(missing_ok=True)
                staged_candidate.unlink(missing_ok=True)
                raise JobFileError(
                    "file version was adopted, but transaction confirmation failed"
                ) from exc
            if target.exists():
                os.replace(target, staged_candidate)
                renamed = False
        owned_candidate.unlink(missing_ok=True)
        staged_candidate.unlink(missing_ok=True)
        if target is not None:
            target.unlink(missing_ok=True)
        raise
    return get_version(version_id, user_email)


def archive_file(
    file_id: int,
    by: str,
    *,
    opened_version_id: int,
) -> dict[str, Any]:
    """Archive a work file without deleting any retained artifact."""
    from . import collaboration

    db.init_schema()
    now = _utc_now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            _FILE_SELECT
            + " WHERE job_files.id=? AND job_access.user_email=?",
            (file_id, by.strip().lower()),
        ).fetchone()
        if row is None:
            raise JobFileError("job file not found")
        if row["access_role"] not in {"owner", "editor"}:
            raise JobFileError("owner or editor access required")
        if row["archived_at"] is not None:
            raise JobFileError("job file is already archived")
        try:
            collaboration._assert_file_checkout_in_tx(
                conn,
                file_id,
                by,
                opened_version_id,
            )
        except collaboration.CollaborationError as exc:
            raise JobFileError(str(exc)) from exc
        conn.execute(
            "UPDATE job_files SET archived_by=?, archived_at=?, updated_by=?,"
            " updated_at=? WHERE id=?",
            (by, now, by, now, file_id),
        )
        conn.execute(
            "DELETE FROM advisory_locks"
            " WHERE resource_type='job-file' AND resource_id=?"
            " AND holder_email=?",
            (str(file_id), by),
        )
        conn.execute(
            "INSERT INTO job_activity(job_id,job_file_id,kind,message,"
            "actor_email,created_at) VALUES(?,?,?,?,?,?)",
            (
                int(row["job_id"]),
                file_id,
                "job-file-archived",
                f"Archived {row['display_name']}",
                by,
                now,
            ),
        )
    return get_file(file_id, by)


def _transition_row(conn, file_id: int, by: str):
    row = conn.execute(
        _FILE_SELECT + " WHERE job_files.id=? AND job_access.user_email=?",
        (file_id, by.strip().lower()),
    ).fetchone()
    if row is None:
        raise JobFileError("job file not found")
    if row["access_role"] not in {"owner", "editor"}:
        raise JobFileError("owner or editor access required")
    if row["archived_at"] is not None:
        raise JobFileError("archived files cannot be changed")
    return row


def _assert_transition_checkout(
    conn,
    file_id: int,
    by: str,
    opened_version_id: int,
) -> None:
    from . import collaboration

    try:
        collaboration._assert_file_checkout_in_tx(
            conn,
            file_id,
            by,
            opened_version_id,
        )
    except collaboration.CollaborationError as exc:
        raise JobFileError(str(exc)) from exc


def _set_status_and_record_activity(
    conn,
    row,
    status: str,
    by: str,
    now: str,
    message: str,
) -> None:
    file_id = int(row["id"])
    conn.execute(
        "UPDATE job_files SET status=?,updated_by=?,updated_at=? WHERE id=?",
        (status, by, now, file_id),
    )
    jobs._record_activity(  # noqa: SLF001 - shared transaction helper
        conn,
        int(row["job_id"]),
        "job-file-status-changed",
        message,
        by,
        now,
        job_file_id=file_id,
    )


def _get_file_with_current_version(
    file_id: int,
    user_email: str,
) -> dict[str, Any]:
    row = get_file(file_id, user_email)
    row["current_version"] = get_version(
        int(row["current_version_id"]),
        user_email,
    )
    return row


def _version_path(file_id: int, version_number: int) -> Path:
    return (
        versions_root()
        / str(file_id)
        / "versions"
        / f"v{version_number:06d}.mrc"
    )


def _adoption_version_exists_in_db(
    file_id: int,
    version_id: int,
    target: Path,
) -> bool:
    """Check exact durable version identity after uncertain transaction exit."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT file_path FROM job_file_versions"
            " WHERE id=? AND job_file_id=?",
            (version_id, file_id),
        ).fetchone()
    return row is not None and row["file_path"] == str(target)


def _export_reference_id_for_path(target: Path) -> int | None:
    """Return the durable export referencing a path after uncertain exit."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id FROM job_file_exports WHERE file_path=?",
            (str(target),),
        ).fetchone()
    return int(row["id"]) if row is not None else None


def _copy_export_exclusive(
    source: Path,
    export_dir: Path,
    filename: str,
) -> Path:
    """Stream to a new path without ever opening an existing artifact."""
    export_dir.mkdir(parents=True, exist_ok=True)
    for _attempt in range(10):
        target = export_dir / f"{uuid.uuid4().hex}-{filename}"
        try:
            target_file = target.open("xb")
        except FileExistsError:
            continue
        try:
            with target_file, source.open("rb") as source_file:
                shutil.copyfileobj(source_file, target_file)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target
    raise JobFileError("could not allocate a unique export path")


def _safe_export_filename(filename: str) -> str:
    """Return a portable basename suitable for retained export storage."""
    basename = Path(filename.strip()).name
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", basename).strip("-.")
    if not clean:
        raise JobFileError("a valid export filename is required")
    return clean


def _invalidate_approval_and_supersede_exports_in_tx(
    conn,
    file_id: int,
    version_id: int,
    now: str,
) -> None:
    """Invalidate prior release state after a new unapproved version wins."""
    conn.execute(
        "UPDATE job_file_exports SET state='superseded',superseded_at=?,"
        "superseded_by_version_id=? WHERE job_file_id=?"
        " AND state IN ('draft','ready')",
        (now, version_id, file_id),
    )


_FILE_SELECT = (
    "SELECT job_files.*, job_access.role AS access_role,"
    " job_file_versions.version_number AS current_version_number,"
    " job_file_versions.record_count AS current_record_count,"
    " job_file_versions.file_bytes AS current_file_bytes,"
    " job_file_versions.created_by AS current_version_created_by,"
    " job_file_versions.created_at AS current_version_created_at"
    " FROM job_files"
    " JOIN job_access ON job_access.job_id=job_files.job_id"
    " JOIN job_file_versions ON job_file_versions.id=job_files.current_version_id"
)

_VERSION_SELECT = (
    "SELECT job_file_versions.*, job_files.job_id, job_files.display_name,"
    " job_access.role AS access_role"
    " FROM job_file_versions"
    " JOIN job_files ON job_files.id=job_file_versions.job_file_id"
    " JOIN job_access ON job_access.job_id=job_files.job_id"
)

_EXPORT_SELECT = (
    "SELECT job_file_exports.*,job_files.job_id,job_files.display_name,"
    " job_file_versions.version_number,job_access.role AS access_role"
    " FROM job_file_exports"
    " JOIN job_files ON job_files.id=job_file_exports.job_file_id"
    " JOIN job_file_versions ON job_file_versions.id=job_file_exports.version_id"
    " JOIN job_access ON job_access.job_id=job_files.job_id"
)


def _dict(row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _utc_now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
