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
        self.column_calls: list[dict] = []

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

    def columns(self, spec, **kwargs):
        self.column_calls.append({"spec": spec, **kwargs})
        return [_FakeColumn(self) for _ in range(spec)]


class _FakeColumn:
    def __init__(self, st):
        self._st = st

    def __enter__(self):
        return self._st

    def __exit__(self, exc_type, exc, tb):
        return False


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


def test_approved_header_aligns_material_bell_immediately_before_account(
    monkeypatch,
):
    fake_st = _FakeStreamlit()
    app = _app(monkeypatch, fake_st, "cat@smith.edu")
    order = []
    monkeypatch.setattr(
        app.authz, "get_user", lambda _email: {"status": "approved"}
    )
    monkeypatch.setattr(
        app.operation_notifications,
        "render_header_bell",
        lambda _email: order.append("notifications"),
    )
    original_popover = fake_st.popover

    @contextmanager
    def ordered_popover(label, **kwargs):
        order.append(label)
        with original_popover(label, **kwargs):
            yield fake_st

    fake_st.popover = ordered_popover

    app._render_auth_header()

    assert order == ["notifications", "Account"]
    assert fake_st.column_calls == [{
        "spec": 2, "gap": "small", "vertical_alignment": "center",
    }]
    assert fake_st.popovers == [{
        "label": "Account", "icon": ":material/account_circle:",
    }]


def test_pending_header_keeps_account_and_does_not_query_notifications(monkeypatch):
    fake_st = _FakeStreamlit()
    app = _app(monkeypatch, fake_st, "pending@smith.edu")
    monkeypatch.setattr(
        app.authz, "get_user", lambda _email: {"status": "pending"}
    )
    monkeypatch.setattr(
        app.operation_notifications,
        "render_header_bell",
        lambda _email: (_ for _ in ()).throw(AssertionError("bell rendered")),
    )

    app._render_auth_header()

    assert [popover["label"] for popover in fake_st.popovers] == ["Account"]
    assert [button["label"] for button in fake_st.buttons] == ["Sign out"]
