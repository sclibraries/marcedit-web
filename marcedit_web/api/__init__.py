"""Flask API for the independent, not-yet-production service."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import sqlite3
from typing import Optional
from urllib.parse import urlsplit

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from marcedit_web.api import access, me
from marcedit_web.lib import db, identity, runmode


_STORAGE_PATHS = {
    "MARCEDIT_WEB_DB_PATH": "marcedit.db",
    "MARCEDIT_WEB_AUDIT_DIR": "audit",
    "MARCEDIT_WEB_TASKS_ROOT": "tasks",
    "MARCEDIT_WEB_UPLOADS_ROOT": "uploads",
    "MARCEDIT_WEB_JOB_FILES_ROOT": "job-files",
    "MARCEDIT_WEB_OPERATIONS_ROOT": "operations",
    "MARCEDIT_WEB_SNAPSHOTS_ROOT": "snapshots",
}
_PLACEHOLDERS = ("replace", "placeholder", "paste-secret", "changeme")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    database: Path
    origin: str
    url_prefix: str
    port: int
    dev_user: Optional[str]


def _refuse(message: str) -> None:
    raise RuntimeError(message)


def _url(raw: str):
    try:
        parsed = urlsplit(raw)
        parsed.port
    except ValueError as exc:
        raise RuntimeError("MARCEDIT_WEB_PUBLIC_URL is invalid.") from exc
    if (
        not raw
        or any(char.isspace() for char in raw)
        or "\\" in raw
        or parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "%" in parsed.netloc
    ):
        _refuse("Configure an absolute public URL without credentials, query, or fragment.")
    path = parsed.path or "/"
    if not re.fullmatch(r"/[A-Za-z0-9_/-]*", path) or "//" in path:
        _refuse("Use a simple public URL path without encoded or dot segments.")
    host = parsed.hostname
    if ":" in host:
        host = "[{}]".format(host)
    port = parsed.port
    default_port = 443 if parsed.scheme == "https" else 80
    origin = "{}://{}".format(parsed.scheme, host)
    if port is not None and port != default_port:
        origin += ":{}".format(port)
    return parsed, origin, path.rstrip("/") + "/"


def _writable_directory(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return (
        path.is_dir()
        and bool(mode & 0o222)
        and bool(mode & 0o111)
        and os.access(path, os.W_OK | os.X_OK)
    )


def _validate_data_root(raw: str) -> Path:
    if not raw:
        _refuse("MARCEDIT_WEB_DATA_ROOT is required.")
    candidate = Path(raw)
    if not candidate.is_absolute():
        _refuse("MARCEDIT_WEB_DATA_ROOT must be absolute.")
    root = candidate.resolve()
    probe = root
    while not probe.exists():
        probe = probe.parent
    if not _writable_directory(probe):
        _refuse("MARCEDIT_WEB_DATA_ROOT must be writable.")
    return root


def _within_data_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def load_settings() -> Settings:
    """Validate startup configuration and bind all storage to one data root."""
    if runmode.is_public():
        _refuse("The API cannot run in public mode.")

    root = _validate_data_root(os.environ.get("MARCEDIT_WEB_DATA_ROOT", "").strip())
    for name, leaf in _STORAGE_PATHS.items():
        if name not in os.environ:
            os.environ[name] = str(root / leaf)
        resolved = Path(os.environ[name]).resolve()
        if not _within_data_root(resolved, root):
            _refuse("Every storage path must resolve inside MARCEDIT_WEB_DATA_ROOT.")

    raw_url = os.environ.get("MARCEDIT_WEB_PUBLIC_URL", "")
    parsed, origin, url_prefix = _url(raw_url)
    secret = identity.proxy_secret()
    dev_value = os.environ.get("MARCEDIT_WEB_DEV_USER", "").strip()
    if dev_value not in ("", "0") and not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", dev_value
    ):
        _refuse("MARCEDIT_WEB_DEV_USER must be an email address or 0.")
    dev_user = dev_value.lower() if dev_value not in ("", "0") else None

    if dev_user:
        if identity.is_prod() or secret:
            _refuse("Development user mode cannot run with production authentication or a proxy secret.")
        if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            _refuse("Development user mode requires a loopback public URL.")
    else:
        if not identity.is_prod():
            _refuse("Configure production authentication or development user mode.")
        if (
            secret is None
            or len(secret) < 64
            or any(marker in secret.lower() for marker in _PLACEHOLDERS)
        ):
            _refuse("Configure a non-placeholder proxy secret of at least 64 characters.")
        if parsed.scheme != "https":
            _refuse("Production requires an HTTPS public URL.")

    try:
        port = int(os.environ.get("MARCEDIT_WEB_PORT", "8503"))
    except ValueError as exc:
        raise RuntimeError("MARCEDIT_WEB_PORT must be a valid TCP port.") from exc
    if not 1 <= port <= 65535:
        _refuse("MARCEDIT_WEB_PORT must be a valid TCP port.")

    return Settings(
        database=Path(os.environ["MARCEDIT_WEB_DB_PATH"]).resolve(),
        origin=origin,
        url_prefix=url_prefix,
        port=port,
        dev_user=dev_user,
    )


def _read_schema_version(path: Path):
    """Read the schema version without creating, migrating, or writing a DB."""
    if not path.is_file():
        return None
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT version FROM _schema_version").fetchone()
        return int(row[0]) if row else None
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise
    finally:
        connection.close()


def _error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def create_app() -> Flask:
    settings = load_settings()
    try:
        version = _read_schema_version(settings.database)
    except sqlite3.Error as exc:
        raise RuntimeError("The database schema cannot be checked safely.") from exc
    if version is not None and version > db.SCHEMA_VERSION:
        _refuse("The database schema is newer than this API supports.")

    db.init_schema()
    app = Flask(__name__)
    app.config["API_PORT"] = settings.port
    app.config["API_URL_PREFIX"] = settings.url_prefix
    app.config["PUBLIC_ORIGIN"] = settings.origin

    @app.after_request
    def add_response_headers(response):
        response.headers["X-MarcEdit-Api"] = "1"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        status = error.code or 500
        return _error("http-error", "The request could not be completed.", status)

    @app.errorhandler(Exception)
    def unexpected_error(exception):
        logger.exception("Unhandled API exception")
        return _error("internal-error", "An unexpected error occurred.", 500)

    @app.before_request
    def enforce_api_access():
        failure = access.check_request(settings)
        return _error(*failure) if failure is not None else None

    @app.get("/api/v1/health")
    def health():
        try:
            current = _read_schema_version(settings.database)
        except (OSError, sqlite3.Error, ValueError):
            current = None
        healthy = current == db.SCHEMA_VERSION
        return jsonify({"ok": healthy}), 200 if healthy else 503

    app.add_url_rule("/api/v1/me", endpoint="me", view_func=me.get_me, methods=["GET"])

    return app
