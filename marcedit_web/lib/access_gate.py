# marcedit_web/lib/access_gate.py
"""Private-unit authorization gate (TASK-088).

Sits at the top of ``App.py`` in private mode, after the sign-in header
and before ``st.navigation(...).run()``. Approved users proceed (their
role cached in session_state); everyone else gets a friendly screen and
``st.stop()``. No-op in public mode.

The decision is factored out of the rendering so it is unit-testable
without a Streamlit runtime — mirrors ``session.enforce_auth``.
"""
from __future__ import annotations

from . import authz, runmode
from .audit import audit_event
from .identity import current_user


def _resolve_user() -> str:
    """Current user, preferring a session-cached value when present."""
    try:
        import streamlit as st
        cached = st.session_state.get("user")
        if cached:
            return cached
    except Exception:
        pass
    return current_user()


def gate_decision(user: str | None = None) -> authz.Decision:
    """Resolve + authorize the current user. Pure; safe to unit-test."""
    if user is None:
        user = _resolve_user()
    return authz.authorize(user)


_SCREENS = {
    "denied": (
        "**Sign-in required.** This deployment requires a Five-College "
        "Google login. Use the *Sign in with Google* control at the top "
        "right, then refresh this tab."
    ),
    "pending": (
        "**Your account is awaiting approval.** An administrator must "
        "approve your account before you can use the cataloging tools. "
        "You'll have access once they do — check back shortly."
    ),
    "revoked": (
        "**Access revoked.** Your account no longer has access. Contact "
        "your library systems team if you believe this is in error."
    ),
}


def enforce_access() -> None:
    """Render-and-stop for non-approved users; cache role for approved.

    No-op in public mode (the public unit is anonymous by design).
    """
    if runmode.is_public():
        return

    import streamlit as st

    user = _resolve_user()
    decision = gate_decision(user)
    if decision.outcome == "approved":
        st.session_state["role"] = decision.role
        return

    audit_event(f"auth.{decision.outcome}", user=user)
    st.error(_SCREENS.get(decision.outcome, _SCREENS["denied"]))
    st.stop()
