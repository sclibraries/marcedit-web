"""Session-state shape and upload helpers.

Per-session keys live in `st.session_state`. State NEVER persists across
sessions — that's the confirmed v2 scope. Closing the browser tab
discards everything (the per-session temp dir survives until the
container restarts but is not reattached to a new session).

State keys:

    user                  identity from REMOTE_USER/eppn, or "anonymous"
    store                 RecordStore | None (replaces v1's records list)
    issues_cache          dict[str, list[Issue]]
    editor_text           str | None (set when MarcEditor dirties)
    editor_dirty          bool
    tasks_palette_state   list[Operation] (form-builder rows)

In v1 we held the parsed records in `records: list[pymarc.Record]` and
the raw bytes in `raw_bytes`. v2 replaces both with a single
:class:`RecordStore` that disk-backs the raw bytes and lazy-parses
individual records on access — this is what fixes the 100K-record crash.

The Diff page namespaces its own session keys under the `diff_` prefix
so it can run independently of the rest of the app state.
"""

from __future__ import annotations

import logging
import tempfile
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pymarc import Record

from . import quotas, runmode, upload_persistence
from .audit import audit_event
from .identity import ANONYMOUS, current_user, is_anonymous, is_prod
from .record_store import RecordStore

logger = logging.getLogger("marcedit_web.session")

_PUBLIC_MAX_UPLOAD_BYTES = 5 * 1024 * 1024     # 5 MB anonymous cap
_PRIVATE_MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB authenticated cap


def max_upload_bytes() -> int:
    """Resolved upload size ceiling for the current run mode.

    Override with ``MARCEDIT_WEB_MAX_UPLOAD_BYTES`` (operational tuning).
    Public default is deliberately smaller than private to bound
    anonymous abuse on the shared public process (TASK-088).
    """
    import os
    raw = os.environ.get("MARCEDIT_WEB_MAX_UPLOAD_BYTES", "").strip()
    if raw.isdigit():
        return int(raw)
    return _PUBLIC_MAX_UPLOAD_BYTES if runmode.is_public() else _PRIVATE_MAX_UPLOAD_BYTES

# Single source of truth for the state-key shape. `init()` sets each one
# to its default below; later code reads them via `st.session_state[…]`.
STATE_DEFAULTS: dict[str, Any] = {
    "user": "",
    "store": None,
    "issues_cache": {},
    "editor_text": None,
    "editor_dirty": False,
    "tasks_palette_state": [],
    "upload_bytes_total": 0,
}


def init() -> None:
    """Idempotently install state defaults and capture the active user.

    Safe to call from any page's top-of-script. The `user` key is set
    once per session — re-running the script doesn't overwrite it.
    After identity is captured, ``restore_active_upload`` rehydrates
    the loaded batch from the SQL ``uploads`` table for OAuth-signed
    users whose ``session_state["store"]`` is missing (typical after
    a hard browser refresh).
    """
    import streamlit as st

    for key, default in STATE_DEFAULTS.items():
        if key not in st.session_state:
            # Lists and dicts in STATE_DEFAULTS are SHARED across calls;
            # copy them so per-session mutation doesn't leak globally.
            if isinstance(default, (list, dict)):
                st.session_state[key] = type(default)()
            else:
                st.session_state[key] = default
    if not st.session_state.get("user"):
        st.session_state["user"] = current_user()
    restore_active_upload()


def restore_active_upload() -> None:
    """Reattach the active SQL upload row to ``session_state["store"]``.

    No-op when:
      * The current user is anonymous (anonymous users get no SQL
        row by design; refresh loses their upload).
      * ``session_state["store"]`` already holds something (we never
        clobber an in-flight session's store).
      * The user has no active upload row.
      * The active row's on-disk file vanished — the row is cleared
        in that case so the next refresh isn't stuck in a loop.

    Successful restore audits ``upload-restored`` once.
    """
    import streamlit as st

    if st.session_state.get("store") is not None:
        return
    user = st.session_state.get("user") or ""
    if is_anonymous(user):
        return
    row = upload_persistence.get_active_upload(user)
    if row is None:
        return
    path = Path(row["file_path"])
    if not path.exists():
        logger.info(
            "active upload row for %s points at missing %s; clearing",
            user, path,
        )
        upload_persistence.clear_active_upload(user)
        return
    try:
        store = RecordStore.from_path(path)
    except Exception as exc:  # noqa: BLE001 — corrupt file shouldn't crash boot
        logger.warning(
            "failed to restore upload from %s: %s", path, exc
        )
        upload_persistence.clear_active_upload(user)
        return
    # Restore the filename from the SQL row (RecordStore.from_path
    # would otherwise set it to "upload.mrc", the on-disk name).
    store._filename = row["filename"]
    st.session_state["store"] = store
    audit_event(
        "upload-restored",
        user=user,
        filename=row["filename"],
        records=row["record_count"],
        size=row["file_bytes"],
    )


def init_page() -> None:
    """Combined per-page bootstrap: state defaults + prod-auth gate.

    Every page's top-of-script should call this *before* any other
    Streamlit calls. In prod mode (``MARCEDIT_WEB_PROD=1``) without a
    Shibboleth identity header, this short-circuits the render and
    shows the login-needed banner via :func:`enforce_auth`.
    """
    init()
    enforce_auth()


def enforce_auth() -> None:
    """Refuse anonymous traffic in prod mode.

    Behavior matrix:

    * dev mode (``MARCEDIT_WEB_PROD`` unset) — no-op.
    * prod mode + authenticated user — no-op.
    * prod mode + anonymous user — emit
      ``anonymous-action-refused`` audit event, render the friendly
      banner, and ``st.stop()``.

    The banner explains what the cataloger needs to do (refresh after
    completing the institutional login) and surfaces a support link.
    Pages below the call never run, so individual action endpoints
    (save, run, upload, download) don't need their own auth check.
    """
    if not is_prod():
        return
    user = _current_user_for_enforcement()
    if not is_anonymous(user):
        return

    import streamlit as st

    audit_event(
        "anonymous-action-refused",
        user=ANONYMOUS,
        page=_page_label(),
    )
    st.error(
        "**Sign-in required.** This deployment requires a Smith / "
        "InCommon login before catalogers can upload or transform "
        "MARC records. "
        "If you just signed in and still see this page, refresh "
        "the browser tab. Otherwise contact your library systems team."
    )
    st.caption(
        "Server-side action refusal is logged. No request data was "
        "processed."
    )
    st.stop()


def _current_user_for_enforcement() -> str:
    """Return the current user, preferring session_state if init() ran."""
    import streamlit as st

    cached = st.session_state.get("user")
    if cached:
        return cached
    return current_user()


def _page_label() -> str:
    """Best-effort current-page identifier for the audit record.

    Streamlit doesn't expose a stable "current page name" API. The
    closest is the script run context's main script path; if that
    fails we degrade gracefully to "unknown" — the audit row still
    captures the refusal, just without the page hint.
    """
    try:
        import streamlit as st  # local import: keeps this module testable
        ctx = st.runtime.scriptrunner.get_script_run_ctx()
        if ctx and ctx.main_script_path:
            return Path(ctx.main_script_path).name
    except Exception:
        pass
    return "unknown"


def _session_records_dir() -> Path:
    """Return (and lazily create) the per-session temp dir for record bytes."""
    import streamlit as st

    key = "records_tmp_dir"
    if key not in st.session_state:
        st.session_state[key] = tempfile.mkdtemp(prefix="marcedit-web-records-")
    return Path(st.session_state[key])


def handle_upload(uploaded_file) -> dict:
    """Read `uploaded_file` from a Streamlit uploader and update state.

    `uploaded_file` is whatever `st.file_uploader(...)` returned — either
    `None` (no upload yet) or a `BytesIO`-shaped object with `.name` and
    `.getvalue()`. Returns a summary dict the page can render:
      `{filename, total, malformed}`.

    When no file is supplied (or the bytes are empty) we clear the
    previous upload's state so the page doesn't lie about what's
    loaded. For OAuth-identified users, "clear" also wipes the
    persisted upload row so the next refresh doesn't rehydrate it.

    TASK-051: for non-anonymous users the bytes are also written to a
    stable per-user path under ``data/uploads/<slug>/upload.mrc`` and
    a SQL row records the active upload. On refresh, ``init()`` calls
    ``restore_active_upload()`` to reattach.
    """
    import streamlit as st

    user = current_user_id()

    # Early cap check — reject before reading bytes (TASK-088).
    # Shape mirrors the existing quota-rejection path so callers behave
    # identically: {"filename", "total": 0, "malformed": 0, "error": str}.
    size_hint = getattr(uploaded_file, "size", None)
    if size_hint is not None and size_hint > max_upload_bytes():
        cap_mb = max_upload_bytes() // (1024 * 1024)
        return {
            "filename": getattr(uploaded_file, "name", None),
            "total": 0,
            "malformed": 0,
            "error": f"File exceeds the {cap_mb} MB limit.",
        }

    if uploaded_file is None:
        st.session_state["store"] = None
        st.session_state["issues_cache"] = {}
        st.session_state["editor_text"] = None
        st.session_state["editor_dirty"] = False
        upload_persistence.clear_active_upload(user)
        return {"filename": None, "total": 0, "malformed": 0}

    raw = uploaded_file.getvalue()
    size = len(raw)

    try:
        quotas.check_upload(size, kind="upload")
        new_total = quotas.check_session_aggregate(
            st.session_state.get("upload_bytes_total", 0),
            size,
        )
    except quotas.QuotaExceeded as exc:
        audit_event(
            "upload-rejected",
            user=user,
            filename=uploaded_file.name,
            size=size,
            reason=exc.kind,
            limit=exc.limit,
        )
        return {
            "filename": uploaded_file.name,
            "total": 0,
            "malformed": 0,
            "error": str(exc),
        }

    # Pick the storage dir based on identity:
    #   * anonymous → per-session tmp (wiped on container restart;
    #     not retained across refresh — by design)
    #   * signed-in → stable per-user dir under data/uploads/
    if is_anonymous(user):
        store_dir = _session_records_dir()
    else:
        store_dir = upload_persistence.persisted_upload_dir(user)

    store = RecordStore.from_bytes(
        raw,
        tmp_dir=store_dir,
        filename=uploaded_file.name,
    )
    if not is_anonymous(user):
        upload_persistence.record_upload(
            user=user,
            filename=uploaded_file.name,
            file_path=store.path,
            record_count=store.count(),
            file_bytes=size,
        )
    st.session_state["store"] = store
    st.session_state["upload_bytes_total"] = new_total
    # Reset derived state — anything the previous file populated is now
    # stale and would mislead later pages.
    st.session_state["issues_cache"] = {}
    st.session_state["editor_text"] = None
    st.session_state["editor_dirty"] = False
    logger.info(
        "loaded upload: %s records, %s malformed",
        store.count(),
        store.malformed_count(),
    )
    audit_event(
        "upload-accepted",
        user=user,
        filename=uploaded_file.name,
        size=size,
        records=store.count(),
        malformed=store.malformed_count(),
    )
    return {
        "filename": uploaded_file.name,
        "total": store.count(),
        "malformed": store.malformed_count(),
    }


def has_upload() -> bool:
    """True when a file has been uploaded and parsed in this session."""
    import streamlit as st

    store = st.session_state.get("store")
    return store is not None and store.count() > 0


def require_upload(blurb: str) -> bool:
    """Shared "upload required" gate for the render modules.

    Returns True iff a file is already loaded. Otherwise renders the
    standard banner ("Upload a `.mrc` file on **Home** to {blurb}.")
    and returns False, so the caller can short-circuit:

        if not session.require_upload("validate records"):
            return

    ``blurb`` is the feature-specific tail — keep it lowercase and
    verb-led ("dedupe within the loaded batch", not "Dedupe").
    """
    if has_upload():
        return True
    import streamlit as st

    st.info(
        f"Upload a `.mrc` file on **Home** to {blurb}. "
        "This feature reads records already in this session."
    )
    return False


def current_store() -> Optional[RecordStore]:
    """Return the active RecordStore, or None if nothing is loaded."""
    import streamlit as st

    return st.session_state.get("store")


def current_filename() -> Optional[str]:
    store = current_store()
    return store.filename if store is not None else None


def stamped_filename(base: str, suffix: str = ".mrc") -> str:
    """Return ``{base}_{YYYYMMDD_HHMMSS}{suffix}`` for a download.

    Single owner of the download-filename timestamp shape (TASK-078c);
    callers pass their base (and a non-default suffix when needed).
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{stamp}{suffix}"


def current_user_id() -> str:
    """Return the active user captured at init() (cached), or ANONYMOUS.

    The single read-point for the per-session identity (TASK-078b). The value
    is set once by init() via current_user() (OAuth + proxy-attestation gated,
    TASK-073); callers read the cached value rather than re-evaluating.
    """
    import streamlit as st

    return st.session_state.get("user") or ANONYMOUS


def record_count() -> int:
    """Number of live records, or 0 if nothing loaded.

    Used by sidebar status lines on every page — cheap and never
    materializes records.
    """
    store = current_store()
    return store.count() if store is not None else 0


def current_records() -> list[Record]:
    """Backward-compat shim: materialize all records as a list.

    Deprecated. New code should use `current_store().iter_records()`
    to avoid loading the whole batch into memory. Kept here so any
    surviving v1 caller still works while we migrate.
    """
    store = current_store()
    if store is None:
        return []
    warnings.warn(
        "session.current_records() materializes the entire batch; "
        "use session.current_store() and store.iter_records() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return list(store.iter_records())


def current_raw_bytes() -> Optional[bytes]:
    """Serialize the current store back to MARC bytes, or None if empty.

    In v1 this returned the original upload bytes verbatim. In v2 it
    serializes via :py:meth:`RecordStore.to_mrc_bytes` so the download
    reflects any edits applied via MarcEditor / Tasks since upload.
    """
    store = current_store()
    if store is None:
        return None
    return store.to_mrc_bytes()
