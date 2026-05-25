"""Identity shim for Shibboleth-aware deployment.

Prod will run behind a reverse proxy (nginx + mod_shib) that injects
`REMOTE_USER` and `eppn` HTTP headers on the protected location. In dev,
those headers are absent and we fall back to `"anonymous"`.

`current_user()` reads from `st.context.headers` when called in a
Streamlit runtime context, and accepts an explicit `headers` mapping
for tests (and any future non-Streamlit caller).

No PII is logged from this module — the active user is shown only in
the UI sidebar.
"""

from __future__ import annotations

import os
from typing import Mapping

ANONYMOUS = "anonymous"


_TRUTHY = {"1", "true", "yes", "on"}


def is_prod() -> bool:
    """True when the app is running in production-auth mode.

    Set via ``MARCEDIT_WEB_PROD=1`` in the container environment.
    Production mode requires every request to carry a Shibboleth
    identity header (``REMOTE_USER`` or ``eppn``); anonymous sessions
    are refused with a friendly banner + audit entry.

    Dev mode is the default (env var unset) and lets anonymous users
    in for local testing.
    """
    return os.environ.get("MARCEDIT_WEB_PROD", "").strip().lower() in _TRUTHY


def is_anonymous(user: str | None) -> bool:
    """True when ``user`` is unset or the anonymous sentinel."""
    return not user or user == ANONYMOUS


def current_user(headers: Mapping[str, str] | None = None) -> str:
    """Return the active user identifier, or `"anonymous"` in dev.

    Header precedence: `REMOTE_USER` first, then `eppn`. Both are
    Shibboleth conventions; reverse-proxy configuration decides which
    one (or both) lands on inbound requests.

    Pass `headers` explicitly to bypass the Streamlit lookup — useful in
    tests and for any future non-Streamlit caller. When `headers` is
    None, we try `st.context.headers` and fall back to an empty mapping
    if Streamlit is not available or the context is empty.
    """
    if headers is None:
        headers = _streamlit_headers()
    raw = (headers.get("REMOTE_USER") or "").strip()
    if raw:
        return raw
    raw = (headers.get("eppn") or "").strip()
    if raw:
        return raw
    return ANONYMOUS


def _streamlit_headers() -> Mapping[str, str]:
    """Best-effort fetch of HTTP headers from the active Streamlit context.

    Returns an empty mapping when:
      * Streamlit isn't installed (we're in a unit test).
      * `st.context` isn't available (pre-1.37 Streamlit, or no active run).
      * Any other access error — we treat absence as "anonymous".

    Never raises.
    """
    try:
        import streamlit as st  # local import: keeps this module testable
        # `st.context.headers` exists on Streamlit 1.37+. Older versions
        # don't ship `st.context` at all; the AttributeError lands us in
        # the except branch below.
        return dict(st.context.headers)
    except Exception:
        return {}
