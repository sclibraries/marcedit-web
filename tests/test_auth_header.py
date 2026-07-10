"""Auth-header layout guard (TASK-146).

The sign-in / Account control used a ``st.columns([6, 1])`` spacer to
sit flush right; on narrow viewports the 1-part column shrank below the
label width and the text broke mid-word ("Accoun / t"). The header now
right-aligns a content-sized keyed container and pins the label to one
line. These tests exist so the no-wrap guard and the keyed container it
is scoped to cannot be dropped independently.
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from types import SimpleNamespace


class _FakeStreamlit:
    def __init__(self):
        self.container_keys: list[str | None] = []
        self.markdowns: list[str] = []
        self.popovers: list[dict] = []
        self.buttons: list[dict] = []
        self.captions: list[str] = []

    @contextmanager
    def container(self, key=None, **kwargs):
        self.container_keys.append(key)
        yield self

    @contextmanager
    def popover(self, label, **kwargs):
        self.popovers.append({"label": label, **kwargs})
        yield self

    def markdown(self, body, unsafe_allow_html=False):
        self.markdowns.append(str(body))

    def button(self, label, **kwargs):
        self.buttons.append({"label": label, **kwargs})
        return False

    def caption(self, message):
        self.captions.append(str(message))


def _app(monkeypatch, fake_st, email):
    monkeypatch.setenv("MARCEDIT_WEB_MODE", "private")
    import marcedit_web.App as app

    app = importlib.reload(app)
    monkeypatch.setattr(app, "st", fake_st)
    monkeypatch.setattr(
        app,
        "identity",
        SimpleNamespace(
            is_oauth_configured=lambda: True,
            oauth_user=lambda: email,
        ),
    )
    return app


def _style_blocks(fake_st) -> str:
    return " ".join(m for m in fake_st.markdowns if "<style>" in m)


def test_signed_in_header_pins_label_to_one_line(monkeypatch):
    fake_st = _FakeStreamlit()
    app = _app(monkeypatch, fake_st, "cat@smith.edu")

    app._render_auth_header()

    assert fake_st.container_keys == ["auth_header"]
    style = _style_blocks(fake_st)
    # The no-wrap rule must be scoped to the keyed container it relies on.
    assert "st-key-auth_header" in style
    assert "white-space: nowrap" in style
    assert "max-content" in style
    assert [p["label"] for p in fake_st.popovers] == ["Account"]


def test_signed_out_header_uses_same_guard(monkeypatch):
    fake_st = _FakeStreamlit()
    app = _app(monkeypatch, fake_st, None)

    app._render_auth_header()

    assert fake_st.container_keys == ["auth_header"]
    assert "white-space: nowrap" in _style_blocks(fake_st)
    assert [b["label"] for b in fake_st.buttons] == ["Sign in with Google"]
