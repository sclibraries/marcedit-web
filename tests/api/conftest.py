from __future__ import annotations

import pytest


STORAGE_SETTINGS = (
    "MARCEDIT_WEB_DB_PATH",
    "MARCEDIT_WEB_AUDIT_DIR",
    "MARCEDIT_WEB_TASKS_ROOT",
    "MARCEDIT_WEB_UPLOADS_ROOT",
    "MARCEDIT_WEB_JOB_FILES_ROOT",
    "MARCEDIT_WEB_OPERATIONS_ROOT",
    "MARCEDIT_WEB_SNAPSHOTS_ROOT",
)


@pytest.fixture
def configure_dev(monkeypatch, tmp_path):
    def configure(data_root=None, public_url="http://localhost:8080/marcedit-next/"):
        for name in STORAGE_SETTINGS:
            monkeypatch.setenv(name, "")
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(
            "MARCEDIT_WEB_DATA_ROOT", str(data_root or tmp_path / "data")
        )
        monkeypatch.setenv("MARCEDIT_WEB_PUBLIC_URL", public_url)
        monkeypatch.setenv("MARCEDIT_WEB_DEV_USER", "api-test@example.invalid")
        monkeypatch.setenv("MARCEDIT_WEB_ADMIN_EMAILS", "")
        monkeypatch.setenv("MARCEDIT_WEB_ALLOWED_DOMAINS", "")
        monkeypatch.delenv("MARCEDIT_WEB_PROD", raising=False)
        monkeypatch.delenv("MARCEDIT_WEB_PROXY_SECRET", raising=False)
        monkeypatch.setenv("MARCEDIT_WEB_MODE", "private")
        monkeypatch.delenv("MARCEDIT_WEB_PORT", raising=False)

    return configure
