"""Session-state shape and upload helpers.

Per-session keys live in `st.session_state`. State NEVER persists across
sessions — that's the confirmed scope for v1. Closing the browser tab
discards everything.

State keys (see the plan for the full design):

    user                  identity from REMOTE_USER/eppn, or "anonymous"
    filename              original upload filename
    raw_bytes             original upload bytes (untouched)
    records               list[pymarc.Record] (parsed on upload)
    malformed_count       int (records pymarc couldn't decode)
    issues_cache          dict[str, list[Issue]]
                          e.g. {"preflight": [...], "rules": [...]}
    editor_text           str | None (set when MarcEditor dirties)
    editor_dirty          bool
    tasks_palette_state   list[Operation] (form-builder rows)

The Diff page namespaces its own session keys under the `diff_` prefix
so it can run independently of the rest of the app state.

The parsing logic is split out into `parse_uploaded_bytes` (pure) so it
can be unit-tested without a Streamlit runtime context. The Streamlit-
flavored helpers (`init`, `handle_upload`, `download_button`) are thin
wrappers around that.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from pymarc import MARCReader, Record

from .identity import current_user

logger = logging.getLogger("marcedit_web.session")

# Single source of truth for the state-key shape. `init()` sets each one
# to its default below; later code reads them via `st.session_state[…]`.
STATE_DEFAULTS: dict[str, Any] = {
    "user": "",
    "filename": None,
    "raw_bytes": None,
    "records": [],
    "malformed_count": 0,
    "issues_cache": {},
    "editor_text": None,
    "editor_dirty": False,
    "tasks_palette_state": [],
}


def parse_uploaded_bytes(data: bytes) -> tuple[list[Record], int]:
    """Parse a raw `.mrc` byte blob into records + malformed count.

    Pure function: never touches `st.session_state`, never logs PII.
    Uses pymarc in permissive mode so a single bad record doesn't abort
    the whole upload — instead the parse stays on the rails and the bad
    record is counted as malformed and dropped.

    Returns `(records, malformed_count)`.
    """
    if not data:
        return [], 0
    records: list[Record] = []
    malformed = 0
    reader = MARCReader(io.BytesIO(data), to_unicode=True, permissive=True)
    for record in reader:
        if record is None:
            malformed += 1
            continue
        records.append(record)
    return records, malformed


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
        st.session_state["filename"] = None
        st.session_state["raw_bytes"] = None
        st.session_state["records"] = []
        st.session_state["malformed_count"] = 0
        st.session_state["issues_cache"] = {}
        st.session_state["editor_text"] = None
        st.session_state["editor_dirty"] = False
        return {"filename": None, "total": 0, "malformed": 0}

    raw = uploaded_file.getvalue()
    records, malformed = parse_uploaded_bytes(raw)
    st.session_state["filename"] = uploaded_file.name
    st.session_state["raw_bytes"] = raw
    st.session_state["records"] = records
    st.session_state["malformed_count"] = malformed
    # Reset derived state — anything the previous file populated is now
    # stale and would mislead later pages.
    st.session_state["issues_cache"] = {}
    st.session_state["editor_text"] = None
    st.session_state["editor_dirty"] = False
    logger.info(
        "loaded upload: %s records, %s malformed",
        len(records),
        malformed,
    )
    return {
        "filename": uploaded_file.name,
        "total": len(records),
        "malformed": malformed,
    }


def has_upload() -> bool:
    """True when a file has been uploaded and parsed in this session."""
    import streamlit as st

    return bool(st.session_state.get("records")) or bool(
        st.session_state.get("raw_bytes")
    )


def current_filename() -> str | None:
    import streamlit as st

    return st.session_state.get("filename")


def current_records() -> list[Record]:
    import streamlit as st

    return list(st.session_state.get("records") or [])


def current_raw_bytes() -> bytes | None:
    import streamlit as st

    return st.session_state.get("raw_bytes")
