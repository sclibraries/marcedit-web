from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from urllib.request import urlopen

import pytest
from waitress import create_server

from marcedit_web.api import create_app
from marcedit_web.lib import db


STORAGE_SETTINGS = (
    "MARCEDIT_WEB_DB_PATH",
    "MARCEDIT_WEB_AUDIT_DIR",
    "MARCEDIT_WEB_TASKS_ROOT",
    "MARCEDIT_WEB_UPLOADS_ROOT",
    "MARCEDIT_WEB_JOB_FILES_ROOT",
    "MARCEDIT_WEB_OPERATIONS_ROOT",
    "MARCEDIT_WEB_SNAPSHOTS_ROOT",
)


def configure_dev(monkeypatch, data_root, public_url="http://localhost:8080/marcedit-next/"):
    for name in STORAGE_SETTINGS:
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MARCEDIT_WEB_DATA_ROOT", str(data_root))
    monkeypatch.setenv("MARCEDIT_WEB_PUBLIC_URL", public_url)
    monkeypatch.setenv("MARCEDIT_WEB_DEV_USER", "1")
    monkeypatch.delenv("MARCEDIT_WEB_PROD", raising=False)
    monkeypatch.delenv("MARCEDIT_WEB_PROXY_SECRET", raising=False)
    monkeypatch.setenv("MARCEDIT_WEB_MODE", "private")
    monkeypatch.delenv("MARCEDIT_WEB_PORT", raising=False)


@pytest.mark.parametrize(
    "broken_setting",
    [
        "data-root-missing",
        "data-root-relative",
        "data-root-read-only",
        "public-url-missing",
        "public-url-invalid",
        "production-http",
        "production-secret-missing",
        "production-secret-short",
        "production-secret-placeholder",
        "dev-user-production-1",
        "dev-user-production-true",
        "dev-user-production-yes",
        "dev-user-production-on",
        "dev-user-secret",
        "dev-user-public-url",
        "public-mode",
        "neither-mode",
        "storage-outside-root",
        "storage-symlink-outside-root",
    ],
)
def test_invalid_configuration_refuses_startup(broken_setting, monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    configure_dev(monkeypatch, data_root)

    if broken_setting == "data-root-missing":
        monkeypatch.delenv("MARCEDIT_WEB_DATA_ROOT")
    elif broken_setting == "data-root-relative":
        monkeypatch.setenv("MARCEDIT_WEB_DATA_ROOT", "relative-data")
    elif broken_setting == "data-root-read-only":
        data_root.mkdir()
        data_root.chmod(0o555)
    elif broken_setting == "public-url-missing":
        monkeypatch.delenv("MARCEDIT_WEB_PUBLIC_URL")
    elif broken_setting == "public-url-invalid":
        monkeypatch.setenv("MARCEDIT_WEB_PUBLIC_URL", "https://example.invalid/a/../b")
    elif broken_setting.startswith("production-"):
        monkeypatch.setenv("MARCEDIT_WEB_DEV_USER", "0")
        monkeypatch.setenv("MARCEDIT_WEB_PROD", "true")
        monkeypatch.setenv("MARCEDIT_WEB_PUBLIC_URL", "https://example.invalid/marcedit-next/")
        if broken_setting == "production-http":
            monkeypatch.setenv("MARCEDIT_WEB_PUBLIC_URL", "http://example.invalid/marcedit-next/")
            monkeypatch.setenv("MARCEDIT_WEB_PROXY_SECRET", "x" * 64)
        elif broken_setting == "production-secret-short":
            monkeypatch.setenv("MARCEDIT_WEB_PROXY_SECRET", "short")
        elif broken_setting == "production-secret-placeholder":
            monkeypatch.setenv("MARCEDIT_WEB_PROXY_SECRET", "replace" + "x" * 64)
        else:
            monkeypatch.delenv("MARCEDIT_WEB_PROXY_SECRET", raising=False)
    elif broken_setting.startswith("dev-user-production-"):
        monkeypatch.setenv(
            "MARCEDIT_WEB_PROD", broken_setting.removeprefix("dev-user-production-")
        )
    elif broken_setting == "dev-user-secret":
        monkeypatch.setenv("MARCEDIT_WEB_PROXY_SECRET", "x" * 64)
    elif broken_setting == "dev-user-public-url":
        monkeypatch.setenv("MARCEDIT_WEB_PUBLIC_URL", "http://catalog.example.invalid/marcedit-next/")
    elif broken_setting == "public-mode":
        monkeypatch.setenv("MARCEDIT_WEB_MODE", "public")
    elif broken_setting == "neither-mode":
        monkeypatch.setenv("MARCEDIT_WEB_DEV_USER", "0")
        monkeypatch.setenv("MARCEDIT_WEB_PROD", "0")
    elif broken_setting == "storage-outside-root":
        monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "other.db"))
    elif broken_setting == "storage-symlink-outside-root":
        outside = tmp_path / "outside"
        outside.mkdir()
        data_root.mkdir()
        (data_root / "linked").symlink_to(outside, target_is_directory=True)
        monkeypatch.setenv("MARCEDIT_WEB_AUDIT_DIR", str(data_root / "linked" / "audit"))

    with pytest.raises(RuntimeError):
        create_app()


@pytest.mark.parametrize("prod_value", ["1", "true", "yes", "on"])
def test_real_mode_accepts_identity_production_values(prod_value, monkeypatch, tmp_path):
    configure_dev(
        monkeypatch,
        tmp_path / "data",
        public_url="https://catalog.example.invalid/marcedit-next/",
    )
    monkeypatch.setenv("MARCEDIT_WEB_DEV_USER", "0")
    monkeypatch.setenv("MARCEDIT_WEB_PROD", prod_value)
    monkeypatch.setenv("MARCEDIT_WEB_PROXY_SECRET", "s" * 64)

    assert create_app().config["API_URL_PREFIX"] == "/marcedit-next/"


def test_newer_schema_refuses_before_migration_or_data_change(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    configure_dev(monkeypatch, data_root)
    database = data_root / "marcedit.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE _schema_version (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO _schema_version VALUES (99)")
        connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel VALUES ('synthetic')")

    with pytest.raises(RuntimeError, match="newer"):
        create_app()

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version FROM _schema_version").fetchone() == (99,)
        assert connection.execute("SELECT value FROM sentinel").fetchone() == ("synthetic",)
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("_schema_version",),
            ("sentinel",),
        ]


@pytest.mark.parametrize("database_state", ["missing", "wrong-version"])
def test_health_is_read_only_and_requires_current_schema(database_state, monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    configure_dev(monkeypatch, data_root)
    app = create_app()
    database = data_root / "marcedit.db"

    if database_state == "missing":
        database.unlink()
    else:
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE _schema_version SET version = ?", (db.SCHEMA_VERSION - 1,))
            connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
            connection.execute("INSERT INTO sentinel VALUES ('synthetic')")

    response = app.test_client().get("/api/v1/health")
    assert response.status_code == 503
    assert response.get_json() == {"ok": False}
    if database_state == "missing":
        assert not database.exists()
    else:
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT version FROM _schema_version").fetchone() == (
                db.SCHEMA_VERSION - 1,
            )
            assert connection.execute("SELECT value FROM sentinel").fetchone() == ("synthetic",)


def test_waitress_serves_health_under_configured_url_prefix(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    configure_dev(monkeypatch, data_root)
    monkeypatch.setenv("MARCEDIT_WEB_PORT", "8123")
    app = create_app()
    assert app.config["API_PORT"] == 8123
    assert app.config["API_URL_PREFIX"] == "/marcedit-next/"
    assert app.config["PUBLIC_ORIGIN"] == "http://localhost:8080"
    assert {
        name: Path(os.environ[name]).resolve().relative_to(data_root.resolve())
        for name in STORAGE_SETTINGS
    } == {
        "MARCEDIT_WEB_DB_PATH": Path("marcedit.db"),
        "MARCEDIT_WEB_AUDIT_DIR": Path("audit"),
        "MARCEDIT_WEB_TASKS_ROOT": Path("tasks"),
        "MARCEDIT_WEB_UPLOADS_ROOT": Path("uploads"),
        "MARCEDIT_WEB_JOB_FILES_ROOT": Path("job-files"),
        "MARCEDIT_WEB_OPERATIONS_ROOT": Path("operations"),
        "MARCEDIT_WEB_SNAPSHOTS_ROOT": Path("snapshots"),
    }
    server = create_server(
        app,
        host="127.0.0.1",
        port=0,
        url_prefix=app.config["API_URL_PREFIX"],
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        with urlopen(
            "http://127.0.0.1:{}/marcedit-next/api/v1/health".format(server.effective_port),
            timeout=5,
        ) as response:
            assert response.status == 200
            assert response.read() == b'{"ok":true}\n'
    finally:
        server.trigger.pull_trigger(server.close)
        thread.join(timeout=5)
        server.task_dispatcher.shutdown()
        assert not thread.is_alive()


def test_unexpected_error_is_plain_and_all_responses_are_hardened(monkeypatch, tmp_path):
    configure_dev(monkeypatch, tmp_path / "data")
    app = create_app()

    @app.get("/api/v1/boom")
    def boom():
        raise RuntimeError("/synthetic/private/path")

    response = app.test_client().get("/api/v1/boom")
    assert response.status_code == 500
    assert response.get_json() == {
        "error": {
            "code": "internal-error",
            "message": "An unexpected error occurred.",
        }
    }
    assert b"/synthetic/private/path" not in response.data
    assert b"Traceback" not in response.data
    assert response.headers["X-MarcEdit-Api"] == "1"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_import_startup_and_health_never_attempt_streamlit():
    script = r'''
import importlib.abc
import os
import sys
import tempfile

attempts = []
class NoStreamlit(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "streamlit" or fullname.startswith("streamlit."):
            attempts.append(fullname)
            raise AssertionError("Streamlit import crossed the API boundary")
sys.meta_path.insert(0, NoStreamlit())

with tempfile.TemporaryDirectory() as data_root:
    os.environ["MARCEDIT_WEB_DATA_ROOT"] = data_root
    os.environ["MARCEDIT_WEB_PUBLIC_URL"] = "http://localhost:8080/marcedit-next/"
    os.environ["MARCEDIT_WEB_DEV_USER"] = "1"
    os.environ["MARCEDIT_WEB_MODE"] = "private"
    for name in (
        "MARCEDIT_WEB_PROD",
        "MARCEDIT_WEB_PROXY_SECRET",
        "MARCEDIT_WEB_DB_PATH",
        "MARCEDIT_WEB_AUDIT_DIR",
        "MARCEDIT_WEB_TASKS_ROOT",
        "MARCEDIT_WEB_UPLOADS_ROOT",
        "MARCEDIT_WEB_JOB_FILES_ROOT",
        "MARCEDIT_WEB_OPERATIONS_ROOT",
        "MARCEDIT_WEB_SNAPSHOTS_ROOT",
    ):
        os.environ.pop(name, None)

    from marcedit_web.api import create_app
    response = create_app().test_client().get("/api/v1/health")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}

assert "streamlit" not in sys.modules
assert not attempts, attempts
'''
    env = {"PATH": os.environ.get("PATH", "")}
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
