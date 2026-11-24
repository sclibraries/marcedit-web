from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from flask import g, jsonify, request
from jsonschema import Draft202012Validator, FormatChecker
import pytest
from waitress import create_server

from marcedit_web.api import create_app
from marcedit_web.lib import authz, db


PROXY_SECRET = "synthetic-proxy-secret-" + "s" * 64
ORIGIN = "https://api.example.invalid"


def _configure_proxy(monkeypatch, configure_dev, data_root):
    configure_dev(data_root, public_url=ORIGIN + "/marcedit-next/")
    monkeypatch.setenv("MARCEDIT_WEB_DEV_USER", "0")
    monkeypatch.setenv("MARCEDIT_WEB_PROD", "1")
    monkeypatch.setenv("MARCEDIT_WEB_PROXY_SECRET", PROXY_SECRET)


def _proxy_headers(email):
    return {
        "X-MarcEdit-User": email,
        "X-MarcEdit-Proxy-Attestation": PROXY_SECRET,
        "Origin": ORIGIN,
        "X-MarcEdit-Request": email.lower(),
    }


def _add_user(email, status="approved", role="cataloger"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(email, role, status, created_at) VALUES (?, ?, ?, ?)",
            (email, role, status, "2026-11-24T00:00:00Z"),
        )


def _validate_response(response, schema_name):
    path = (
        Path(__file__).parents[2]
        / "marcedit_web"
        / "schemas"
        / "api"
        / schema_name
    )
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        response.get_json()
    )


@pytest.mark.parametrize(
    "case,email,status,role,path,expected_status,expected_code,audit_kind",
    [
        (
            "missing", None, None, None, "/api/v1/stand-in", 401,
            "signed-out", "anonymous-action-refused",
        ),
        (
            "wrong-attestation", "intruder@example.invalid", None, None,
            "/api/v1/stand-in", 401, "signed-out", "anonymous-action-refused",
        ),
        (
            "pending", "pending@example.invalid", "pending", "cataloger",
            "/api/v1/stand-in", 403, "not-approved", "auth.pending",
        ),
        (
            "revoked", "revoked@example.invalid", "revoked", "cataloger",
            "/api/v1/stand-in", 403, "not-approved", "auth.revoked",
        ),
        (
            "cataloger", "cataloger@example.invalid", "approved", "cataloger",
            "/api/v1/stand-in", 200, None, None,
        ),
        (
            "admin", "admin@example.invalid", "approved", "admin",
            "/api/v1/stand-in", 200, None, None,
        ),
        (
            "cataloger-admin", "cataloger-admin@example.invalid", "approved",
            "cataloger", "/api/v1/admin/stand-in", 403, "admin-only",
            "auth.admin-only",
        ),
    ],
    ids=[
        "missing", "bad-attestation", "pending", "revoked", "cataloger",
        "admin", "admin-route-role",
    ],
)
def test_api_access_table_on_mutating_route(
    case,
    email,
    status,
    role,
    path,
    expected_status,
    expected_code,
    audit_kind,
    monkeypatch,
    tmp_path,
    configure_dev,
):
    _configure_proxy(monkeypatch, configure_dev, tmp_path / "data")
    app = create_app()
    if status:
        _add_user(email, status=status, role=role)
    writes = []

    def write():
        writes.append(g.api_access.email)
        return jsonify({"email": g.api_access.email, "body": request.get_json()})

    app.add_url_rule("/api/v1/stand-in", "write", write, methods=["POST"])
    app.add_url_rule(
        "/api/v1/admin/stand-in", "admin_write", write, methods=["POST"]
    )
    headers = _proxy_headers(email) if email else {}
    if case == "wrong-attestation":
        headers["X-MarcEdit-Proxy-Attestation"] = "wrong"
    response = app.test_client().post(
        path,
        json={"value": "synthetic"},
        headers=headers,
    )

    assert response.status_code == expected_status
    if expected_code:
        assert response.get_json()["error"]["code"] == expected_code
        _validate_response(response, "error.schema.json")
    else:
        assert response.get_json()["email"] == email
        assert writes == [email]
    assert bool(writes) is (expected_status == 200)
    if audit_kind:
        with db.connect() as conn:
            audited = conn.execute(
                "SELECT COUNT(*) FROM audit_events WHERE kind=?",
                (audit_kind,),
            ).fetchone()[0]
        assert audited == 1


@pytest.mark.parametrize(
    "status,role,outcome,expected_role",
    [
        ("pending", "cataloger", "pending", None),
        ("revoked", "cataloger", "revoked", None),
        ("approved", "cataloger", "approved", "cataloger"),
        ("approved", "admin", "approved", "admin"),
    ],
)
def test_me_reports_each_access_decision(
    status, role, outcome, expected_role, monkeypatch, tmp_path, configure_dev
):
    _configure_proxy(monkeypatch, configure_dev, tmp_path / "data")
    app = create_app()
    email = "me@example.invalid"
    _add_user(email, status=status, role=role)

    response = app.test_client().get("/api/v1/me", headers=_proxy_headers(email))

    assert response.status_code == 200
    assert response.get_json() == {
        "email": email,
        "outcome": outcome,
        "role": expected_role,
        "version": 1,
    }
    _validate_response(response, "me.schema.json")


def test_dev_user_is_the_me_identity(monkeypatch, tmp_path, configure_dev):
    configure_dev(tmp_path / "data")
    monkeypatch.setenv("MARCEDIT_WEB_DEV_USER", "Dev.User@Example.invalid")
    response = create_app().test_client().get("/api/v1/me")

    assert response.status_code == 200
    assert response.get_json()["email"] == "dev.user@example.invalid"
    assert response.get_json()["outcome"] == "pending"
    _validate_response(response, "me.schema.json")


def test_spoofed_legacy_headers_cookie_and_body_do_not_change_identity(
    monkeypatch, tmp_path, configure_dev
):
    _configure_proxy(monkeypatch, configure_dev, tmp_path / "data")
    app = create_app()
    alice = "alice@example.invalid"
    _add_user(alice)

    def whoami():
        return jsonify({"email": g.api_access.email, "body": request.get_json()})

    app.add_url_rule("/api/v1/whoami", "whoami", whoami, methods=["POST"])
    headers = _proxy_headers("Alice@Example.invalid")
    headers.update(
        {"REMOTE_USER": "bob@example.invalid", "eppn": "bob@example.invalid"}
    )
    client = app.test_client()
    client.set_cookie("identity", "bob@example.invalid")
    response = client.post(
        "/api/v1/whoami",
        json={"email": "bob@example.invalid"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "email": alice,
        "body": {"email": "bob@example.invalid"},
    }


@pytest.mark.parametrize(
    "origin,opened_as,expected_status,expected_code",
    [
        (None, "alice@example.invalid", 403, "bad-request-origin"),
        (
            "https://other.example.invalid", "alice@example.invalid", 403,
            "bad-request-origin",
        ),
        (ORIGIN, None, 403, "bad-request-origin"),
        (ORIGIN, "bob@example.invalid", 409, "identity-changed"),
    ],
)
def test_mutation_identity_checks_reject_before_reading_body(
    origin,
    opened_as,
    expected_status,
    expected_code,
    monkeypatch,
    tmp_path,
    configure_dev,
):
    _configure_proxy(monkeypatch, configure_dev, tmp_path / "data")
    app = create_app()
    alice = "alice@example.invalid"
    _add_user(alice)
    writes = []

    def write():
        writes.append(request.get_json())
        return jsonify({"ok": True})

    app.add_url_rule("/api/v1/body", "body", write, methods=["POST"])
    headers = {
        "X-MarcEdit-User": alice,
        "X-MarcEdit-Proxy-Attestation": PROXY_SECRET,
    }
    if origin is not None:
        headers["Origin"] = origin
    if opened_as is not None:
        headers["X-MarcEdit-Request"] = opened_as
    response = app.test_client().post(
        "/api/v1/body",
        data='{"broken":',
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == expected_status
    assert response.get_json()["error"]["code"] == expected_code
    assert writes == []
    _validate_response(response, "error.schema.json")


def test_health_is_public_but_unknown_api_paths_still_require_identity(
    monkeypatch, tmp_path, configure_dev
):
    _configure_proxy(monkeypatch, configure_dev, tmp_path / "data")
    client = create_app().test_client()

    assert client.get("/api/v1/health").status_code == 200
    signed_out = client.get("/api/v1/me")
    assert signed_out.status_code == 401
    assert signed_out.get_json()["error"]["code"] == "signed-out"
    _validate_response(signed_out, "error.schema.json")
    response = client.get("/api/v1/unknown")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "signed-out"


def test_role_and_revoke_changes_apply_on_the_next_request(
    monkeypatch, tmp_path, configure_dev
):
    _configure_proxy(monkeypatch, configure_dev, tmp_path / "data")
    app = create_app()
    email = "promoted@example.invalid"
    _add_user(email, status="approved", role="cataloger")
    app.add_url_rule(
        "/api/v1/admin/check",
        "admin_check",
        lambda: jsonify({"email": g.api_access.email}),
        methods=["GET"],
    )
    client = app.test_client()
    headers = _proxy_headers(email)

    first = client.get("/api/v1/admin/check", headers=headers)
    authz.set_role(email, "admin", by="synthetic-test")
    promoted = client.get("/api/v1/admin/check", headers=headers)
    options = client.options("/api/v1/admin/check", headers=headers)
    authz.revoke_user(email, by="synthetic-test")
    revoked = client.get("/api/v1/admin/check", headers=headers)

    assert first.status_code == 403
    assert first.get_json()["error"]["code"] == "admin-only"
    assert promoted.status_code == 200
    assert promoted.get_json() == {"email": email}
    assert options.status_code == 200
    assert not any(
        name.lower().startswith("access-control-")
        for name, _value in options.headers.items()
    )
    assert revoked.status_code == 403
    assert revoked.get_json()["error"]["code"] == "not-approved"


def test_waitress_accepts_hyphenated_identity_and_drops_underscored_header(
    monkeypatch, tmp_path, configure_dev
):
    _configure_proxy(monkeypatch, configure_dev, tmp_path / "data")
    app = create_app()
    email = "waitress@example.invalid"
    _add_user(email)
    app.add_url_rule(
        "/api/v1/who",
        "who",
        lambda: jsonify({"email": g.api_access.email}),
        methods=["GET"],
    )
    server = create_server(
        app, host="127.0.0.1", port=0, url_prefix="/marcedit-next/"
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = "http://127.0.0.1:{}/marcedit-next/api/v1/who".format(
        server.effective_port
    )
    try:
        request_with_identity = Request(
            url,
            headers={
                "X-MarcEdit-User": email,
                "X-MarcEdit-Proxy-Attestation": PROXY_SECRET,
            },
        )
        with urlopen(request_with_identity, timeout=5) as response:
            assert response.status == 200
            assert json.loads(response.read()) == {"email": email}

        request_with_underscore = Request(
            url,
            headers={
                "X_MarcEdit_User": email,
                "X-MarcEdit-Proxy-Attestation": PROXY_SECRET,
            },
        )
        with pytest.raises(HTTPError) as refused:
            urlopen(request_with_underscore, timeout=5)
        assert refused.value.code == 401
    finally:
        server.trigger.pull_trigger(server.close)
        thread.join(timeout=5)
        server.task_dispatcher.shutdown()
        assert not thread.is_alive()


def test_concurrent_first_requests_provision_once(
    monkeypatch, tmp_path, configure_dev
):
    _configure_proxy(monkeypatch, configure_dev, tmp_path / "data")
    monkeypatch.setenv("MARCEDIT_WEB_ALLOWED_DOMAINS", "example.invalid")
    app = create_app()
    email = "racing@example.invalid"
    app.add_url_rule(
        "/api/v1/race",
        "race",
        lambda: jsonify({"email": g.api_access.email}),
        methods=["GET"],
    )
    barrier = threading.Barrier(2)
    original_get_user = authz.get_user

    def synchronized_first_lookup(value):
        result = original_get_user(value)
        if value == email:
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(authz, "get_user", synchronized_first_lookup)

    def get_race():
        return app.test_client().get("/api/v1/race", headers=_proxy_headers(email))

    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(lambda _: get_race(), range(2)))

    assert [response.status_code for response in responses] == [200, 200]
    assert [response.get_json()["email"] for response in responses] == [email, email]
    with db.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM users WHERE email=?", (email,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE kind='auth.approved' AND user_email=?",
            (email,),
        ).fetchone()[0] == 1


def test_revocation_between_lookup_and_insert_stays_authoritative(monkeypatch):
    db.init_schema()
    email = "revoked-race@example.invalid"

    def revoke_during_domain_lookup(_domain):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO users(email, role, status, created_at)"
                " VALUES (?, 'admin', 'revoked', '2026-11-24T00:00:00Z')",
                (email,),
            )
        return True

    monkeypatch.setattr(authz, "_is_allowed_domain", revoke_during_domain_lookup)

    decision = authz.authorize(email)

    assert decision.outcome == "revoked"
    assert decision.role is None
    assert authz.get_user(email)["role"] == "admin"
