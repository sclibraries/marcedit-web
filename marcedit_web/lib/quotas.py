"""Per-feature byte caps and the session-aggregate counter.

Streamlit's framework-level ``maxUploadSize`` is set in
``.streamlit/config.toml`` (currently 2 GB). That's the outer
guardrail. This module adds *stricter, per-feature* caps the app
enforces in code so that:

* A reasonable batch upload (typical: 50–200 MB) fits comfortably;
  a 1.5-GB upload that would survive the framework cap doesn't.
* The tasksfile-import path can't be abused to ship a multi-GB
  "tasksfile" that ends up parsed as text.
* A single session can't drain the disk by repeated uploads inside
  one Streamlit run.

Caps are env-overridable so ops can dial up for a specific batch
without redeploying — set ``MARCEDIT_WEB_MAX_UPLOAD_BYTES`` (and
friends) in the container environment.
"""

from __future__ import annotations

import os


# Defaults tuned for the typical cataloging workflow. Each one is
# overrideable via ``MARCEDIT_WEB_MAX_<NAME>_BYTES``.
# Per-file cap on the Home page batch upload. The RecordStore writes
# the bytes to a per-session temp file at upload time and lazy-reads
# them afterward, so a 1.5 GB batch doesn't pin Python memory beyond
# the transient Streamlit upload buffer. Matches the Diff cap and the
# Streamlit framework cap (``STREAMLIT_SERVER_MAX_UPLOAD_SIZE=2048``).
_DEFAULT_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
# Per-FILE cap on the Diff page. Multi-GB diffs are common cataloging
# workloads; the original marc-diff CLI handled them seamlessly via
# disk streaming. The Streamlit port now mmaps each uploaded file from
# a per-session temp dir, so memory pressure no longer scales with
# file size. The aggregate per-side cap is gone — only per-file
# applies.
_DEFAULT_DIFF_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB per file
_DEFAULT_TASKSFILE_BYTES = 1 * 1024 * 1024    # 1 MB  — tasksfile is text
# Aggregate per session — protects shared disk in the container.
# Bumped past 1 GB so a couple of multi-GB batch uploads in the same
# session don't trip the cap.
_DEFAULT_SESSION_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB


class QuotaExceeded(Exception):
    """Raised when a request would exceed a configured cap.

    ``kind`` is the cap that fired (one of ``"upload"``, ``"diff"``,
    ``"tasksfile"``, ``"session-aggregate"``). ``attempted`` and
    ``limit`` are byte counts. Callers surface a friendly message to
    the user AND emit an audit event so ops sees the rejection.
    """

    def __init__(self, kind: str, attempted: int, limit: int):
        super().__init__(
            f"{kind} size {attempted} bytes exceeds limit {limit} bytes"
        )
        self.kind = kind
        self.attempted = attempted
        self.limit = limit


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(0, value)


def max_upload_bytes() -> int:
    return _env_int("MARCEDIT_WEB_MAX_UPLOAD_BYTES", _DEFAULT_UPLOAD_BYTES)


def max_diff_bytes() -> int:
    return _env_int("MARCEDIT_WEB_MAX_DIFF_BYTES", _DEFAULT_DIFF_BYTES)


def max_tasksfile_bytes() -> int:
    return _env_int("MARCEDIT_WEB_MAX_TASKSFILE_BYTES", _DEFAULT_TASKSFILE_BYTES)


def max_session_bytes() -> int:
    return _env_int("MARCEDIT_WEB_MAX_SESSION_BYTES", _DEFAULT_SESSION_BYTES)


_LIMITS = {
    "upload": max_upload_bytes,
    "diff": max_diff_bytes,
    "tasksfile": max_tasksfile_bytes,
}


def check_upload(size: int, kind: str = "upload") -> int:
    """Raise QuotaExceeded if ``size`` would blow the cap for ``kind``.

    Returns ``size`` unchanged on success so callers can use it inline:
    ``ok_size = quotas.check_upload(len(raw), "upload")``.
    """
    limit_fn = _LIMITS.get(kind)
    if limit_fn is None:
        raise ValueError(f"unknown quota kind: {kind!r}")
    limit = limit_fn()
    if size > limit:
        raise QuotaExceeded(kind, size, limit)
    return size


def check_session_aggregate(running_total: int, increment: int) -> int:
    """Return ``running_total + increment`` if under cap, else raise.

    Streamlit pages call this after a successful per-upload check so
    repeated uploads in one session also bound the disk usage. The
    running total lives in ``st.session_state["upload_bytes_total"]``;
    pages are responsible for persisting the returned value back.
    """
    limit = max_session_bytes()
    new_total = running_total + increment
    if new_total > limit:
        raise QuotaExceeded("session-aggregate", new_total, limit)
    return new_total
