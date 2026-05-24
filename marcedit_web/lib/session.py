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
from pathlib import Path
from typing import Any, Optional

from pymarc import Record

from .identity import current_user
from .record_store import RecordStore

logger = logging.getLogger("marcedit_web.session")

# Single source of truth for the state-key shape. `init()` sets each one
# to its default below; later code reads them via `st.session_state[…]`.
STATE_DEFAULTS: dict[str, Any] = {
    "user": "",
    "store": None,
    "issues_cache": {},
    "editor_text": None,
    "editor_dirty": False,
    "tasks_palette_state": [],
}


def init() -> None:
    """Idempotently install state defaults and capture the active user.

    Safe to call from any page's top-of-script. The `user` key is set
    once per session — re-running the script doesn't overwrite it.
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
    previous upload's state so the page doesn't lie about what's loaded.
    """
    import streamlit as st

    if uploaded_file is None:
        st.session_state["store"] = None
        st.session_state["issues_cache"] = {}
        st.session_state["editor_text"] = None
        st.session_state["editor_dirty"] = False
        return {"filename": None, "total": 0, "malformed": 0}

    raw = uploaded_file.getvalue()
    tmp_dir = _session_records_dir()
    store = RecordStore.from_bytes(
        raw,
        tmp_dir=tmp_dir,
        filename=uploaded_file.name,
    )
    st.session_state["store"] = store
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


def current_store() -> Optional[RecordStore]:
    """Return the active RecordStore, or None if nothing is loaded."""
    import streamlit as st

    return st.session_state.get("store")


def current_filename() -> Optional[str]:
    store = current_store()
    return store.filename if store is not None else None


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
