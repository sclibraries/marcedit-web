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
    current_job_id        int | None (selected private upload job)

In v1 we held the parsed records in `records: list[pymarc.Record]` and
the raw bytes in `raw_bytes`. v2 replaces both with a single
:class:`RecordStore` that disk-backs the raw bytes and lazy-parses
individual records on access — this is what fixes the 100K-record crash.

The Diff page namespaces its own session keys under the `diff_` prefix
so it can run independently of the rest of the app state.
"""

from __future__ import annotations

import logging
import os
import tempfile
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pymarc import Record

from . import job_files, jobs, quotas, runmode, upload_persistence
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
    "current_job_id": None,
    "job_file_id": None,
    "job_file_version_id": None,
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
    if not restore_job_file_context():
        restore_active_upload()
    # Flush toasts queued by the PREVIOUS run's action handlers (TASK-136):
    # queue_toast + this flush is what lets feedback survive st.rerun()
    # and st.switch_page.
    for message, icon in st.session_state.pop("pending_toasts", []):
        st.toast(message, icon=icon)


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
    if row.get("job_id") is not None:
        linked_file = next(
            (
                file_row
                for file_row in job_files.list_files(
                    int(row["job_id"]), user, include_archived=True
                )
                if file_row.get("original_upload_id") == row["id"]
            ),
            None,
        )
        if linked_file is not None:
            open_job_file(int(linked_file["id"]))
            audit_event(
                "upload-restored",
                user=user,
                filename=row["filename"],
                records=row["record_count"],
                size=row["file_bytes"],
            )
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
    if row.get("job_id") is not None:
        st.session_state["current_job_id"] = row["job_id"]
    audit_event(
        "upload-restored",
        user=user,
        filename=row["filename"],
        records=row["record_count"],
        size=row["file_bytes"],
    )


def restore_job_file_context() -> bool:
    """Handle a cached file id after rechecking access and current version.

    Returns ``True`` whenever file context existed, including when access was
    revoked and the context was cleared. That prevents an invalid authoritative
    id from falling through to legacy upload restoration.
    """
    import streamlit as st

    file_id = st.session_state.get("job_file_id")
    if file_id is None:
        return False
    user = current_user_id()
    try:
        row = job_files.get_file(int(file_id), user)
        version = job_files.get_current_version(int(file_id), user)
    except job_files.JobFileError:
        detach_loaded_batch(None)
        return True
    cached_version_id = st.session_state.get("job_file_version_id")
    if (
        st.session_state.get("store") is None
        or cached_version_id != version["id"]
    ):
        open_job_file(int(row["id"]))
    return True


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


def _clear_mutation_previews(state) -> None:
    """Release disk-backed previews tied to the store being replaced."""
    from . import batch_replace, quick_batch

    batch_replace.cleanup_preview(state.pop("batch_replace_preview", None))
    quick_batch.cleanup_preview(state.pop("quick_batch_preview", None))
    state.pop("folio_safe_fix_preview", None)


def handle_upload(
    uploaded_file,
    *,
    job_id: int | None = None,
    description: str = "",
) -> dict:
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
    cap = max_upload_bytes()
    if size_hint is not None and size_hint > cap:
        cap_mb = cap // (1024 * 1024)
        return {
            "filename": getattr(uploaded_file, "name", None),
            "total": 0,
            "malformed": 0,
            "error": f"File exceeds the {cap_mb} MB limit.",
        }

    if uploaded_file is None:
        _clear_mutation_previews(st.session_state)
        st.session_state["store"] = None
        st.session_state["job_file_id"] = None
        st.session_state["job_file_version_id"] = None
        st.session_state["issues_cache"] = {}
        st.session_state["editor_text"] = None
        st.session_state["editor_dirty"] = False
        upload_persistence.clear_active_upload(user)
        return {"filename": None, "total": 0, "malformed": 0}

    # TASK-132: never materialize the upload — the widget already holds
    # one full copy in server RAM; ingest streams straight to disk.
    size = getattr(uploaded_file, "size", None)
    if size is None:
        uploaded_file.seek(0, os.SEEK_END)
        size = uploaded_file.tell()

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
    selected_job_id = job_id
    if is_anonymous(user):
        store_dir = _session_records_dir()
    else:
        store_dir = upload_persistence.persisted_job_upload_dir(
            user,
            selected_job_id,
        )

    store = RecordStore.from_file(
        uploaded_file,
        tmp_dir=store_dir,
        filename=uploaded_file.name,
    )
    if not is_anonymous(user):
        upload = upload_persistence.record_upload(
            user=user,
            filename=uploaded_file.name,
            file_path=store.path,
            record_count=store.count(),
            file_bytes=size,
            job_id=selected_job_id,
        )
        if upload["job_id"] is not None:
            work_file = job_files.attach_file(
                job_id=int(upload["job_id"]),
                user_email=user,
                source_path=Path(upload["file_path"]),
                filename=upload["filename"],
                record_count=int(upload["record_count"]),
                file_bytes=int(upload["file_bytes"]),
                upload_id=int(upload["id"]),
                description=description,
            )
            _set_job_file_context(work_file)
        else:
            st.session_state["job_file_id"] = None
            st.session_state["job_file_version_id"] = None
    st.session_state["store"] = store
    _clear_mutation_previews(st.session_state)
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


def _set_job_file_context(
    row: dict[str, Any],
    *,
    version_id: int | None = None,
) -> None:
    import streamlit as st

    if st.session_state.get("current_job_id") != row["job_id"]:
        st.session_state["current_job_id"] = row["job_id"]
    st.session_state["job_file_id"] = row["id"]
    st.session_state["job_file_version_id"] = (
        row["current_version_id"] if version_id is None else version_id
    )


def open_job_file(file_id: int) -> dict[str, Any]:
    """Open the accessible current immutable version of one work file."""
    import streamlit as st

    user = current_user_id()
    row = job_files.get_file(file_id, user)
    version = job_files.get_current_version(file_id, user)
    store = RecordStore.from_path(Path(version["file_path"]))
    store._filename = row["display_name"]
    _clear_mutation_previews(st.session_state)
    st.session_state["store"] = store
    _set_job_file_context(row, version_id=int(version["id"]))
    st.session_state["quick_load_mode"] = False
    st.session_state["issues_cache"] = {}
    st.session_state["editor_text"] = None
    st.session_state["editor_dirty"] = False
    return {
        **row,
        "job_file_id": row["id"],
        "total": store.count(),
        "job_file_version_id": version["id"],
    }


def adopt_current_candidate(
    *,
    candidate_path: Path,
    source_kind: str,
    label: str,
    summary: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Adopt candidate bytes for the open job file and reopen that version."""
    import streamlit as st

    file_id = st.session_state.get("job_file_id")
    opened_version_id = st.session_state.get("job_file_version_id")
    if file_id is None or opened_version_id is None:
        raise job_files.JobFileError(
            "This change requires a file opened from a job."
        )
    created = job_files.adopt_candidate(
        file_id=int(file_id),
        opened_version_id=int(opened_version_id),
        user_email=current_user_id(),
        candidate_path=Path(candidate_path),
        source_kind=source_kind,
        label=label,
        summary=summary,
        validation=validation,
    )
    open_job_file(int(file_id))
    return created


def current_job_file() -> dict[str, Any] | None:
    """Return the accessible cached work file, clearing stale context."""
    import streamlit as st

    file_id = st.session_state.get("job_file_id")
    if file_id is None:
        return None
    try:
        return job_files.get_file(int(file_id), current_user_id())
    except job_files.JobFileError:
        detach_loaded_batch(None)
        return None


def replace_current_store_from_bytes(
    raw: bytes,
    *,
    filename: str,
    job_id: int | None = None,
) -> RecordStore:
    """Replace the live store from trusted MARC bytes.

    Used by persisted rollback/restore flows after the bytes were already
    accepted into the application. It mirrors upload storage choices so a
    signed-in restore also survives refresh via the active upload row.
    """
    import streamlit as st

    user = current_user_id()
    if is_anonymous(user):
        store_dir = _session_records_dir()
    else:
        store_dir = upload_persistence.persisted_job_upload_dir(user, job_id)

    store = RecordStore.from_bytes(raw, tmp_dir=store_dir, filename=filename)
    if not is_anonymous(user):
        upload_persistence.record_upload(
            user=user,
            filename=filename,
            file_path=store.path,
            record_count=store.count(),
            file_bytes=len(raw),
            job_id=job_id,
        )

    st.session_state["store"] = store
    _clear_mutation_previews(st.session_state)
    st.session_state["issues_cache"] = {}
    st.session_state["editor_text"] = None
    st.session_state["editor_dirty"] = False
    return store


def replace_current_store_from_path(
    source_path: Path,
    *,
    filename: str,
    job_id: int | None = None,
) -> RecordStore:
    """Replace the live store by streaming a trusted on-disk MRC source."""
    import streamlit as st

    user = current_user_id()
    if is_anonymous(user):
        store_dir = _session_records_dir()
    else:
        store_dir = upload_persistence.persisted_job_upload_dir(user, job_id)

    with Path(source_path).open("rb") as source:
        store = RecordStore.from_file(
            source,
            tmp_dir=store_dir,
            filename=filename,
        )
    if not is_anonymous(user):
        upload_persistence.record_upload(
            user=user,
            filename=filename,
            file_path=store.path,
            record_count=store.count(),
            file_bytes=store.path.stat().st_size,
            job_id=job_id,
        )

    st.session_state["store"] = store
    _clear_mutation_previews(st.session_state)
    st.session_state["issues_cache"] = {}
    st.session_state["editor_text"] = None
    st.session_state["editor_dirty"] = False
    return store


def load_persisted_upload(upload_id: int) -> dict:
    """Load one durable upload row into the current Streamlit session."""
    import streamlit as st

    user = current_user_id()
    row = jobs.get_upload_for_user(upload_id, user)
    path = Path(row["file_path"])
    if not path.exists():
        upload_persistence.clear_active_upload(user)
        return {
            "filename": row["filename"],
            "total": 0,
            "malformed": 0,
            "error": "The stored MARC file is missing.",
        }

    store = RecordStore.from_path(path)
    store._filename = row["filename"]
    st.session_state["store"] = store
    _clear_mutation_previews(st.session_state)
    # On Home the Job selectbox owns ``current_job_id`` (key=...), and
    # Streamlit rejects ANY assignment to a widget-owned key — even of the
    # identical value. Home only lists the selected job's files, so the
    # value is already right there; only write when actually switching jobs
    # (Jobs-page flow, where no widget owns the key). TASK-127.
    if st.session_state.get("current_job_id") != row["job_id"]:
        st.session_state["current_job_id"] = row["job_id"]
    st.session_state["issues_cache"] = {}
    st.session_state["editor_text"] = None
    st.session_state["editor_dirty"] = False
    if row["user_email"] == user:
        upload_persistence.activate_upload(user, upload_id)
    return {
        "filename": row["filename"],
        "total": store.count(),
        "malformed": store.malformed_count(),
        "error": None,
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


def detach_loaded_batch(file_path) -> None:
    """Drop the loaded batch when it is backed by ``file_path`` (TASK-128).

    Hard-deleting a durable upload unlinks its bytes; if that file backs
    the session's store, every later disk read (Loaded-batch download,
    View, Editor) would raise FileNotFoundError. Delete handlers call this
    after ``jobs.remove_upload(..., delete_file=True)`` so the session
    falls back to the "no file loaded" state. Resets the same keys
    :func:`load_persisted_upload` writes.
    """
    import streamlit as st

    store = st.session_state.get("store")
    store_path = getattr(store, "path", None)
    if file_path is not None and (
        store_path is None or Path(store_path) != Path(file_path)
    ):
        return
    st.session_state["store"] = None
    st.session_state["job_file_id"] = None
    st.session_state["job_file_version_id"] = None
    _clear_mutation_previews(st.session_state)
    st.session_state["issues_cache"] = {}
    st.session_state["editor_text"] = None
    st.session_state["editor_dirty"] = False


def queue_toast(message: str, icon: str | None = None) -> None:
    """Queue a toast for the NEXT script run (TASK-136).

    Action handlers end in ``st.rerun()`` or ``st.switch_page`` — a direct
    ``st.toast`` there dies with the current run. ``init()`` flushes the
    queue at the top of every page, so the toast shows wherever the
    cataloger lands.
    """
    import streamlit as st

    st.session_state.setdefault("pending_toasts", []).append((message, icon))


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
    try:
        return store.to_mrc_bytes()
    except FileNotFoundError:
        # The backing file can vanish outside this session's control — a
        # collaborator hard-deleting a shared upload we have loaded. Treat
        # it as "nothing to download" rather than crashing the page.
        return None
