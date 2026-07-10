"""High-level snapshot actions shared by render flows."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import provenance
from .identity import is_anonymous


def record_job_snapshot(
    *,
    job_id: int | None,
    user_email: str,
    kind: str,
    label: str,
    before_path: Path | None = None,
    after_path: Path | None = None,
    before_bytes: bytes | None = None,
    after_bytes: bytes | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist a job snapshot when the current context can own one."""
    if job_id is None or is_anonymous(user_email):
        return None
    return provenance.create_snapshot(
        job_id=job_id,
        user_email=user_email,
        kind=kind,
        label=label,
        before_path=before_path,
        after_path=after_path,
        before_bytes=before_bytes,
        after_bytes=after_bytes,
        summary=summary,
    )


def record_edit_snapshot(
    *,
    job_id: int | None,
    user_email: str,
    label: str,
    before_path: Path | None = None,
    after_path: Path | None = None,
    before_bytes: bytes | None = None,
    after_bytes: bytes | None = None,
    record_index: int | None,
    source: str,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist a standard edit snapshot with record/source provenance."""
    payload = dict(summary or {})
    payload["record_index"] = record_index
    payload["source"] = source
    return record_job_snapshot(
        job_id=job_id,
        user_email=user_email,
        kind="edit",
        label=label,
        before_path=before_path,
        after_path=after_path,
        before_bytes=before_bytes,
        after_bytes=after_bytes,
        summary=payload,
    )


@contextmanager
def staged_store_path(store):
    """Materialize a logical store to a temporary path and always clean it."""
    workdir = Path(tempfile.mkdtemp(prefix="marcedit-web-snapshot-stage-"))
    path = workdir / "batch.mrc"
    try:
        store.write_mrc_to(path)
        yield path
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
