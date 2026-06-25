"""High-level snapshot actions shared by render flows."""

from __future__ import annotations

from typing import Any

from . import provenance
from .identity import is_anonymous


def record_job_snapshot(
    *,
    job_id: int | None,
    user_email: str,
    kind: str,
    label: str,
    before_bytes: bytes,
    after_bytes: bytes,
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
        before_bytes=before_bytes,
        after_bytes=after_bytes,
        summary=summary,
    )
