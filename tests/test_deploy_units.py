"""Tests for checked-in systemd deployment units."""

from __future__ import annotations

from pathlib import Path


def test_private_systemd_unit_runs_readiness_before_streamlit():
    """TASK-084: private startup must fail loud if the DB is not writable."""
    unit = Path("deploy/marcedit-web-private.service").read_text()

    assert (
        "ExecStartPre=/var/www/html/marcedit-web/.venv/bin/python "
        "-m marcedit_web.ops.health"
    ) in unit


def test_public_systemd_unit_stays_db_free():
    """The public light tier must not touch the private catalog DB."""
    unit = Path("deploy/marcedit-web-public.service").read_text()

    assert "marcedit_web.ops.health" not in unit
    assert "MARCEDIT_WEB_DB_PATH" not in unit
