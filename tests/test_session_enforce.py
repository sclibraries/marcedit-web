"""Tests for marcedit_web.lib.session.enforce_auth (Stage 21 prod gate).

We exercise the gate without booting Streamlit — the helper falls back
to ``current_user()`` when ``st.session_state`` lookups fail, and we
stub the Streamlit ``st`` module enough to capture the calls.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from marcedit_web.lib import session
from marcedit_web.lib.identity import ANONYMOUS


class _FakeSt:
    """Minimal stand-in for the streamlit module used by enforce_auth.

    Records ``error``, ``caption``, and ``stop`` calls. Raises a custom
    ``Stopped`` exception out of ``stop`` so the test can verify the
    short-circuit happened.
    """

    class Stopped(Exception):
        pass

    def __init__(self, *, user: str | None):
        self.session_state = {"user": user} if user is not None else {}
        self.errors: list[str] = []
        self.captions: list[str] = []
        self.stopped = False
        # `runtime.scriptrunner.get_script_run_ctx` is hit by
        # _page_label — make the helper return None so we don't
        # depend on a real Streamlit script context.
        self.runtime = types.SimpleNamespace(
            scriptrunner=types.SimpleNamespace(
                get_script_run_ctx=lambda: None
            )
        )

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def caption(self, msg: str) -> None:
        self.captions.append(msg)

    def stop(self) -> None:
        self.stopped = True
        raise self.Stopped()


@pytest.fixture
def fake_st(monkeypatch):
    def _install(user: str | None):
        fake = _FakeSt(user=user)
        # session._current_user_for_enforcement does `import streamlit
        # as st`; intercept the module import so our fake is what gets
        # imported. Same for the audit module's writes (we want the
        # write to land in tmp_path; the caller handles MARCEDIT_WEB_AUDIT_DIR).
        monkeypatch.setitem(sys.modules, "streamlit", fake)
        return fake

    return _install


# ---------------------------------------------------------------------------
# Dev mode (env unset): no-op regardless of identity
# ---------------------------------------------------------------------------


def test_dev_mode_with_anonymous_user_no_op(monkeypatch, fake_st):
    monkeypatch.delenv("MARCEDIT_WEB_PROD", raising=False)
    fake = fake_st(user=ANONYMOUS)
    session.enforce_auth()  # should not stop, should not error
    assert fake.stopped is False
    assert fake.errors == []


def test_dev_mode_with_named_user_no_op(monkeypatch, fake_st):
    monkeypatch.delenv("MARCEDIT_WEB_PROD", raising=False)
    fake = fake_st(user="alice@example.edu")
    session.enforce_auth()
    assert fake.stopped is False
    assert fake.errors == []


# ---------------------------------------------------------------------------
# Prod mode: anonymous → refuse, named → no-op
# ---------------------------------------------------------------------------


def test_prod_mode_named_user_passes(monkeypatch, fake_st):
    monkeypatch.setenv("MARCEDIT_WEB_PROD", "1")
    fake = fake_st(user="alice@example.edu")
    session.enforce_auth()
    assert fake.stopped is False
    assert fake.errors == []


def test_prod_mode_anonymous_stops_and_audits(
    monkeypatch, fake_st, tmp_path,
):
    monkeypatch.setenv("MARCEDIT_WEB_PROD", "1")
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path))
    fake = fake_st(user=ANONYMOUS)
    with pytest.raises(_FakeSt.Stopped):
        session.enforce_auth()
    assert fake.stopped is True
    assert fake.errors and "Sign-in required" in fake.errors[0]
    # Audit row landed.
    files = list(tmp_path.glob("audit-*.log"))
    assert len(files) == 1
    rows = [json.loads(line) for line in files[0].read_text().splitlines() if line]
    assert rows
    assert rows[0]["kind"] == "anonymous-action-refused"
    assert rows[0]["user"] == "anonymous"


def test_prod_mode_empty_user_treated_as_anonymous(
    monkeypatch, fake_st, tmp_path,
):
    """A session_state["user"] = "" is functionally anonymous."""
    monkeypatch.setenv("MARCEDIT_WEB_PROD", "1")
    monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(tmp_path))
    fake = fake_st(user="")
    with pytest.raises(_FakeSt.Stopped):
        session.enforce_auth()
    assert fake.stopped is True
