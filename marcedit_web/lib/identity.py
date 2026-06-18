"""Identity shim for Shibboleth-aware deployment.

Two identity sources coexist (TASK-047):

1. **Google OAuth** via Streamlit native ``st.login`` / ``st.user``.
   Operators opt in by providing ``[auth.google]`` credentials in
   ``.streamlit/secrets.toml``. Streamlit drives the OIDC flow,
   issues a session cookie, and exposes the signed-in user via
   ``st.user.email``.
2. **Shibboleth** via reverse-proxy headers (``REMOTE_USER`` /
   ``eppn``). This is the production path on the campus deployment.

``current_user()`` prefers OAuth when a session is signed in;
otherwise it falls back to the Shibboleth headers; otherwise it
returns the anonymous sentinel. Both paths can be live at once —
local-dev operators run OAuth while prod runs behind nginx+Shib.

No PII is logged from this module — the active user is shown only
in the UI sidebar.
"""

from __future__ import annotations

import hmac
import os
from typing import Mapping

ANONYMOUS = "anonymous"


_TRUTHY = {"1", "true", "yes", "on"}


_PROXY_SECRET_ENV = "MARCEDIT_WEB_PROXY_SECRET"
_ATTESTATION_HEADER = "X-MarcEdit-Proxy-Attestation"


def proxy_secret() -> str | None:
    """Return the configured proxy-attestation secret, or None.

    Read from ``MARCEDIT_WEB_PROXY_SECRET``. Apache injects a matching
    header (``X-MarcEdit-Proxy-Attestation``) on every request it proxies;
    the app trusts ``REMOTE_USER`` / ``eppn`` only when that header matches
    this value. Unset/blank disables header trust entirely (fail-closed).
    """
    raw = os.environ.get(_PROXY_SECRET_ENV, "").strip()
    return raw or None


def _attestation_ok(headers: Mapping[str, str]) -> bool:
    """True iff the request is attested to come through the trusted proxy.

    Fail-closed: returns False when no secret is configured. Uses a
    constant-time compare so the secret can't be recovered by timing.
    """
    secret = proxy_secret()
    if secret is None:
        return False
    supplied = headers.get(_ATTESTATION_HEADER) or ""
    return hmac.compare_digest(supplied, secret)


def is_prod() -> bool:
    """True when the app is running in production-auth mode.

    Set via ``MARCEDIT_WEB_PROD=1`` in the container environment.
    Production mode requires every request to carry an authenticated
    identity (OAuth ``st.user.email`` or a Shibboleth header);
    anonymous sessions are refused with a friendly banner + audit
    entry.

    Dev mode is the default (env var unset) and lets anonymous users
    in for local testing.
    """
    return os.environ.get("MARCEDIT_WEB_PROD", "").strip().lower() in _TRUTHY


def is_anonymous(user: str | None) -> bool:
    """True when ``user`` is unset or the anonymous sentinel."""
    return not user or user == ANONYMOUS


def current_user(headers: Mapping[str, str] | None = None) -> str:
    """Return the active user identifier, or `"anonymous"` in dev.

    Resolution order:
      1. ``st.user.email`` when an OAuth session is logged in.
      2. ``REMOTE_USER`` reverse-proxy header (Shibboleth).
      3. ``eppn`` reverse-proxy header (Shibboleth fallback).
      4. ``ANONYMOUS`` sentinel.

    Pass `headers` explicitly to bypass the Streamlit lookup — useful
    in tests and for any future non-Streamlit caller. When `headers`
    is None, we try `st.context.headers` and fall back to an empty
    mapping if Streamlit is not available or the context is empty.
    Passing an explicit `headers` mapping does NOT disable the OAuth
    check; OAuth still wins because a signed-in operator with a
    Shibboleth header present should be identified by their OAuth
    email, not the proxy header.

    Security contract (TASK-073): the ``REMOTE_USER`` / ``eppn`` headers
    are trusted ONLY when the request carries a valid
    ``X-MarcEdit-Proxy-Attestation`` header matching
    ``MARCEDIT_WEB_PROXY_SECRET``. Absent or invalid attestation yields
    ``ANONYMOUS`` (fail-closed), even if ``REMOTE_USER`` is set. The OAuth
    path is independent of attestation — Streamlit validates that session.
    """
    email = oauth_user()
    if email:
        return email
    if headers is None:
        headers = _streamlit_headers()
    # TASK-073: trust the reverse-proxy identity headers only when the
    # request is attested to have arrived through the trusted Apache proxy.
    # A direct caller to 127.0.0.1:8501 cannot supply a valid attestation,
    # so a forged REMOTE_USER/eppn resolves to ANONYMOUS (fail-closed).
    if not _attestation_ok(headers):
        return ANONYMOUS
    raw = (headers.get("REMOTE_USER") or "").strip()
    if raw:
        return raw
    raw = (headers.get("eppn") or "").strip()
    if raw:
        return raw
    return ANONYMOUS


def oauth_user() -> str | None:
    """Return the signed-in Google OAuth email, or None.

    Defensive against every Streamlit-version skew we've seen:
      * No Streamlit installed (unit-test path).
      * ``st.user`` missing (pre-1.42 Streamlit).
      * ``st.user.is_logged_in`` False (configured but not signed in).
      * ``[auth]`` absent from secrets (``st.user`` raises on access).
      * Any other access error — treated as "no OAuth identity".

    Never raises. Returns the lowercased email when logged in, or
    None otherwise. Trailing/leading whitespace is stripped.
    """
    try:
        import streamlit as st  # local import: keeps this module testable

        user = st.user
        if not getattr(user, "is_logged_in", False):
            return None
        email = getattr(user, "email", None)
        if not email:
            return None
        email = str(email).strip()
        return email or None
    except Exception:
        return None


def is_oauth_configured() -> bool:
    """True when ``[auth]`` is present in ``st.secrets``.

    Drives the sidebar sign-in UI's render decision: only show the
    "Sign in with Google" control when OAuth is actually configured.
    Defensive against secrets-loading errors (the file may not exist
    in dev) — never raises.
    """
    try:
        import streamlit as st

        return "auth" in st.secrets
    except Exception:
        return False


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
