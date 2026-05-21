"""Tests for marcedit_web.lib.identity."""

from __future__ import annotations

from marcedit_web.lib import identity
from marcedit_web.lib.identity import ANONYMOUS, current_user


def test_anonymous_when_no_headers():
    assert current_user(headers={}) == ANONYMOUS


def test_anonymous_when_called_without_streamlit_runtime():
    """Outside a Streamlit run, `st.context.headers` raises — we fall back."""
    assert current_user() == ANONYMOUS


def test_remote_user_header_wins():
    assert current_user(headers={"REMOTE_USER": "rconnell@smith.edu"}) == "rconnell@smith.edu"


def test_eppn_used_when_remote_user_absent():
    assert current_user(headers={"eppn": "rconnell@smith.edu"}) == "rconnell@smith.edu"


def test_remote_user_takes_precedence_over_eppn():
    headers = {
        "REMOTE_USER": "primary@smith.edu",
        "eppn": "secondary@smith.edu",
    }
    assert current_user(headers=headers) == "primary@smith.edu"


def test_empty_string_falls_back():
    """A header present but empty should be treated as absent."""
    assert current_user(headers={"REMOTE_USER": "", "eppn": ""}) == ANONYMOUS


def test_whitespace_trimmed():
    assert current_user(headers={"REMOTE_USER": "  user  "}) == "user"


def test_no_logging_of_user(caplog):
    """current_user() must not log the resolved identifier."""
    import logging

    caplog.set_level(logging.DEBUG, logger="marcedit_web")
    current_user(headers={"REMOTE_USER": "should-not-be-logged@smith.edu"})
    assert all(
        "should-not-be-logged" not in r.getMessage() for r in caplog.records
    )


def test_anonymous_constant_is_exported():
    assert identity.ANONYMOUS == "anonymous"
