"""Tests for marcedit_web.lib.identity."""

from __future__ import annotations

from marcedit_web.lib import identity
from marcedit_web.lib.identity import ANONYMOUS, current_user


_PROXY_SECRET = "test-attestation-secret"


def _attest(monkeypatch, headers):
    """Configure the proxy secret and stamp `headers` with a valid
    attestation, so the Shibboleth header path is trusted (post-TASK-073)."""
    monkeypatch.setenv(identity._PROXY_SECRET_ENV, _PROXY_SECRET)
    return {**headers, identity._ATTESTATION_HEADER: _PROXY_SECRET}


def test_anonymous_when_no_headers():
    assert current_user(headers={}) == ANONYMOUS


def test_anonymous_when_called_without_streamlit_runtime():
    """Outside a Streamlit run, `st.context.headers` raises — we fall back."""
    assert current_user() == ANONYMOUS


def test_remote_user_header_wins(monkeypatch):
    assert current_user(
        headers=_attest(monkeypatch, {"REMOTE_USER": "rconnell@smith.edu"})
    ) == "rconnell@smith.edu"


def test_eppn_used_when_remote_user_absent(monkeypatch):
    assert current_user(
        headers=_attest(monkeypatch, {"eppn": "rconnell@smith.edu"})
    ) == "rconnell@smith.edu"


def test_remote_user_takes_precedence_over_eppn(monkeypatch):
    headers = _attest(monkeypatch, {
        "REMOTE_USER": "primary@smith.edu",
        "eppn": "secondary@smith.edu",
    })
    assert current_user(headers=headers) == "primary@smith.edu"


def test_empty_string_falls_back():
    """A header present but empty should be treated as absent."""
    assert current_user(headers={"REMOTE_USER": "", "eppn": ""}) == ANONYMOUS


def test_whitespace_trimmed(monkeypatch):
    assert current_user(
        headers=_attest(monkeypatch, {"REMOTE_USER": "  user  "})
    ) == "user"


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


# ---------------------------------------------------------------------------
# Stage 21: prod-mode + anonymity predicates
# ---------------------------------------------------------------------------


def test_is_prod_false_when_env_unset(monkeypatch):
    monkeypatch.delenv("MARCEDIT_WEB_PROD", raising=False)
    assert identity.is_prod() is False


def test_is_prod_truthy_for_each_accepted_value(monkeypatch):
    for v in ("1", "true", "TRUE", "Yes", "on"):
        monkeypatch.setenv("MARCEDIT_WEB_PROD", v)
        assert identity.is_prod() is True, f"expected {v!r} to be truthy"


def test_is_prod_falsy_for_unrelated_values(monkeypatch):
    for v in ("0", "false", "no", "off", "  ", "random"):
        monkeypatch.setenv("MARCEDIT_WEB_PROD", v)
        assert identity.is_prod() is False, f"expected {v!r} to be falsy"


def test_is_anonymous_recognizes_sentinel():
    assert identity.is_anonymous(ANONYMOUS) is True
    assert identity.is_anonymous("") is True
    assert identity.is_anonymous(None) is True


def test_is_anonymous_false_for_real_user():
    assert identity.is_anonymous("alice@example.edu") is False


# ---------------------------------------------------------------------------
# TASK-047: Google OAuth identity (st.user) coexisting with Shibboleth
# ---------------------------------------------------------------------------


class _FakeUser:
    """Minimal stand-in for Streamlit's ``st.user`` proxy."""

    def __init__(self, *, is_logged_in=False, email=None):
        self.is_logged_in = is_logged_in
        self.email = email


class _BoomUser:
    """``st.user`` proxy that raises on every attribute access.

    Mirrors Streamlit's real behavior when ``[auth]`` is absent from
    secrets — the proxy raises ``StreamlitAuthError`` instead of
    returning a falsy ``is_logged_in``.
    """

    def __getattr__(self, name):
        raise RuntimeError("simulated Streamlit auth-not-configured")


def _install_fake_user(monkeypatch, fake):
    """Make ``import streamlit as st; st.user`` return ``fake``."""
    import streamlit as st

    monkeypatch.setattr(st, "user", fake, raising=False)


def test_oauth_user_returns_email_when_logged_in(monkeypatch):
    _install_fake_user(
        monkeypatch, _FakeUser(is_logged_in=True, email="alice@example.edu")
    )
    assert identity.oauth_user() == "alice@example.edu"


def test_oauth_user_returns_none_when_not_logged_in(monkeypatch):
    _install_fake_user(monkeypatch, _FakeUser(is_logged_in=False, email=None))
    assert identity.oauth_user() is None


def test_oauth_user_swallows_streamlit_errors(monkeypatch):
    """st.user access raises when [auth] isn't in secrets — must not bubble."""
    _install_fake_user(monkeypatch, _BoomUser())
    assert identity.oauth_user() is None


def test_oauth_user_strips_whitespace(monkeypatch):
    _install_fake_user(
        monkeypatch,
        _FakeUser(is_logged_in=True, email="  alice@example.edu  "),
    )
    assert identity.oauth_user() == "alice@example.edu"


def test_oauth_user_treats_blank_email_as_none(monkeypatch):
    _install_fake_user(monkeypatch, _FakeUser(is_logged_in=True, email="   "))
    assert identity.oauth_user() is None


def test_current_user_prefers_oauth_over_remote_user(monkeypatch):
    _install_fake_user(
        monkeypatch, _FakeUser(is_logged_in=True, email="alice@example.edu")
    )
    # Shibboleth header is present — OAuth must still win.
    assert (
        current_user(headers={"REMOTE_USER": "shib-user@example.edu"})
        == "alice@example.edu"
    )


def test_current_user_falls_back_to_headers_when_not_logged_in(monkeypatch):
    _install_fake_user(monkeypatch, _FakeUser(is_logged_in=False, email=None))
    assert (
        current_user(headers=_attest(monkeypatch, {"REMOTE_USER": "shib-user@example.edu"}))
        == "shib-user@example.edu"
    )


def test_current_user_falls_back_to_anonymous_when_neither(monkeypatch):
    _install_fake_user(monkeypatch, _FakeUser(is_logged_in=False, email=None))
    assert current_user(headers={}) == ANONYMOUS


def test_is_oauth_configured_true_when_auth_in_secrets(monkeypatch):
    import streamlit as st

    class _FakeSecrets:
        def __contains__(self, key):
            return key == "auth"

    monkeypatch.setattr(st, "secrets", _FakeSecrets(), raising=False)
    assert identity.is_oauth_configured() is True


def test_is_oauth_configured_false_when_auth_missing(monkeypatch):
    import streamlit as st

    class _FakeSecrets:
        def __contains__(self, key):
            return False

    monkeypatch.setattr(st, "secrets", _FakeSecrets(), raising=False)
    assert identity.is_oauth_configured() is False


def test_is_oauth_configured_swallows_secrets_errors(monkeypatch):
    """Secrets file missing entirely → access raises; we return False."""
    import streamlit as st

    class _BoomSecrets:
        def __contains__(self, key):
            raise RuntimeError("secrets.toml missing")

    monkeypatch.setattr(st, "secrets", _BoomSecrets(), raising=False)
    assert identity.is_oauth_configured() is False


# ---------------------------------------------------------------------------
# TASK-073: proxy attestation predicate
# ---------------------------------------------------------------------------


def test_proxy_secret_none_when_unset(monkeypatch):
    monkeypatch.delenv("MARCEDIT_WEB_PROXY_SECRET", raising=False)
    assert identity.proxy_secret() is None


def test_proxy_secret_none_when_blank(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_PROXY_SECRET", "   ")
    assert identity.proxy_secret() is None


def test_proxy_secret_returns_stripped_value(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_PROXY_SECRET", "  s3cr3t  ")
    assert identity.proxy_secret() == "s3cr3t"


def test_attestation_ok_false_when_secret_unset(monkeypatch):
    """Fail closed: no configured secret means no header is ever trusted."""
    monkeypatch.delenv("MARCEDIT_WEB_PROXY_SECRET", raising=False)
    assert identity._attestation_ok(
        {identity._ATTESTATION_HEADER: "anything"}
    ) is False


def test_attestation_ok_true_on_exact_match(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_PROXY_SECRET", "s3cr3t")
    assert identity._attestation_ok(
        {identity._ATTESTATION_HEADER: "s3cr3t"}
    ) is True


def test_attestation_ok_false_on_mismatch(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_PROXY_SECRET", "s3cr3t")
    assert identity._attestation_ok(
        {identity._ATTESTATION_HEADER: "nope"}
    ) is False


def test_attestation_ok_false_when_header_absent(monkeypatch):
    monkeypatch.setenv("MARCEDIT_WEB_PROXY_SECRET", "s3cr3t")
    assert identity._attestation_ok({}) is False


# ---------------------------------------------------------------------------
# TASK-073: current_user() attestation gate
# ---------------------------------------------------------------------------


def test_forged_remote_user_rejected_without_attestation(monkeypatch):
    """A forged REMOTE_USER hitting :8501 directly (no attestation) must NOT
    be trusted — this is the privilege-escalation the ticket closes."""
    monkeypatch.setenv(identity._PROXY_SECRET_ENV, _PROXY_SECRET)
    assert current_user(headers={"REMOTE_USER": "admin@smith.edu"}) == ANONYMOUS


def test_remote_user_trusted_with_valid_attestation(monkeypatch):
    assert current_user(
        headers=_attest(monkeypatch, {"REMOTE_USER": "admin@smith.edu"})
    ) == "admin@smith.edu"


def test_remote_user_rejected_with_wrong_attestation_same_length(monkeypatch):
    monkeypatch.setenv(identity._PROXY_SECRET_ENV, "secretvalue0001")
    headers = {
        "REMOTE_USER": "admin@smith.edu",
        identity._ATTESTATION_HEADER: "secretvalue9999",
    }
    assert current_user(headers=headers) == ANONYMOUS


def test_remote_user_rejected_with_wrong_attestation_diff_length(monkeypatch):
    monkeypatch.setenv(identity._PROXY_SECRET_ENV, "secretvalue0001")
    headers = {
        "REMOTE_USER": "admin@smith.edu",
        identity._ATTESTATION_HEADER: "x",
    }
    assert current_user(headers=headers) == ANONYMOUS


def test_header_identity_failclosed_when_secret_unset(monkeypatch):
    """No configured secret → even a header with an attestation value is
    ignored (fail-closed)."""
    monkeypatch.delenv(identity._PROXY_SECRET_ENV, raising=False)
    headers = {
        "REMOTE_USER": "admin@smith.edu",
        identity._ATTESTATION_HEADER: "anything",
    }
    assert current_user(headers=headers) == ANONYMOUS


def test_oauth_unaffected_by_attestation(monkeypatch):
    """OAuth identity wins even with no secret and no attestation."""
    monkeypatch.delenv(identity._PROXY_SECRET_ENV, raising=False)
    _install_fake_user(
        monkeypatch, _FakeUser(is_logged_in=True, email="alice@example.edu")
    )
    assert current_user(headers={"REMOTE_USER": "shib@x.edu"}) == "alice@example.edu"


def test_forged_admin_header_does_not_grant_admin(monkeypatch):
    """End-to-end: a forged admin REMOTE_USER without attestation must not
    resolve to an admin (the RCE path the ticket closes)."""
    from marcedit_web.lib import task_admin

    monkeypatch.setenv(identity._PROXY_SECRET_ENV, _PROXY_SECRET)
    monkeypatch.setenv("MARCEDIT_WEB_ADMINS", "admin@smith.edu")
    user = current_user(headers={"REMOTE_USER": "admin@smith.edu"})  # no attestation
    assert user == ANONYMOUS
    assert task_admin.is_admin(user) is False


def test_attested_admin_header_grants_admin(monkeypatch):
    from marcedit_web.lib import task_admin

    monkeypatch.setenv("MARCEDIT_WEB_ADMINS", "admin@smith.edu")
    user = current_user(
        headers=_attest(monkeypatch, {"REMOTE_USER": "admin@smith.edu"})
    )
    assert user == "admin@smith.edu"
    assert task_admin.is_admin(user) is True
