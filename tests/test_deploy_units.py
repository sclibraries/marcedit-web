"""Tests for checked-in systemd deployment units."""

from __future__ import annotations

from pathlib import Path

import pytest


def _repo_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        pytest.skip(f"{path} not in build context (running inside the built image)")
    return p.read_text()


def test_private_systemd_unit_runs_readiness_before_streamlit():
    """TASK-084: private startup must fail loud if the DB is not writable."""
    unit = _repo_file("deploy/marcedit-web-private.service")

    assert (
        "ExecStartPre=/var/www/html/marcedit-web/.venv/bin/python "
        "-m marcedit_web.ops.health"
    ) in unit


def test_private_systemd_unit_has_large_batch_memory_guardrails():
    """Reclaim must start below the hard 2 GB service ceiling."""
    unit = _repo_file("deploy/marcedit-web-private.service")
    active = {
        line.strip()
        for line in unit.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "MemoryHigh=1536M" in active
    assert "MemoryMax=2G" in active
    assert "MemorySwapMax=0" not in active


def test_deployment_docs_gate_swap_limit_on_cgroup_v2():
    """RHEL 8 defaults to v1, so the swap directive needs a v2 preflight."""
    docs = _repo_file("docs/deployment.md")

    assert "stat -fc %T /sys/fs/cgroup" in docs
    assert "cgroup2fs" in docs
    assert "MemorySwapMax=0" in docs
    assert "memory.current" in docs
    assert "memory.events" in docs
    assert "MARCEDIT_WEB_MAX_CONCURRENT_BATCHES" in docs


def test_job_file_backup_docs_use_configured_storage_root():
    """Database rows and immutable artifacts need one configurable snapshot."""
    docs = _repo_file("docs/deployment.md")

    assert 'JOB_FILES_ROOT="${MARCEDIT_WEB_JOB_FILES_ROOT:-data/job-files}"' in docs
    assert 'cp -a "$JOB_FILES_ROOT" "$BACKUP_DIR/job-files"' in docs
    assert 'rm -rf "$JOB_FILES_ROOT"' in docs
    assert '"$BACKUP_DIR/job-files" "$JOB_FILES_ROOT"' in docs
    assert "cp -a data/job-files" not in docs


def test_public_systemd_unit_stays_db_free():
    """The public light tier must not touch the private catalog DB."""
    unit = _repo_file("deploy/marcedit-web-public.service")

    assert "marcedit_web.ops.health" not in unit
    assert "MARCEDIT_WEB_DB_PATH" not in unit


def _deploy_file(path: str) -> str:
    """Like _repo_file, but a missing file is a FAILURE when deploy/
    exists (host checkout) — skip only inside the built image, where
    the whole deploy/ tree is unmounted. A silently-skipped watchdog
    test would defeat its purpose (Rule 12)."""
    if not Path("deploy").exists():
        pytest.skip(f"{path} not in build context (running inside the built image)")
    return Path(path).read_text()


def test_watchdog_service_restarts_on_repeated_health_failure():
    """TASK-133: a dead Streamlit Runtime leaves the process alive
    (health 503, ws refused) — invisible to Restart=on-failure by
    construction (TASK-117). The watchdog is the only automatic
    recovery for that state, so it must probe the real health endpoint
    more than once and restart the unit when the probes fail.
    """
    unit = _deploy_file("deploy/marcedit-web-watchdog.service")

    assert "Type=oneshot" in unit
    assert "http://127.0.0.1:8501/marcedit-web/_stcore/health" in unit
    assert "systemctl restart marcedit-web" in unit
    # Probe must demand HTTP 200, not just a TCP connect: the zombie
    # runtime answers connects and returns 503.
    assert "http_code" in unit
    # An intentionally stopped service must stay stopped (maintenance,
    # migrations) — the watchdog only recovers a unit that systemd
    # believes is running (review finding on TASK-133).
    assert "systemctl is-active --quiet marcedit-web" in unit


def test_watchdog_timer_runs_every_two_minutes():
    unit = _deploy_file("deploy/marcedit-web-watchdog.timer")

    assert "OnUnitActiveSec=2min" in unit
    assert "OnBootSec=" in unit
    assert "WantedBy=timers.target" in unit
