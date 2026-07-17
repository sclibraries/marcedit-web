"""Tests for checked-in systemd deployment units."""

from __future__ import annotations

import subprocess
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


def test_job_file_backup_docs_load_production_env_before_resolving_root(tmp_path):
    """Database rows and immutable artifacts need one configurable snapshot."""
    docs = _repo_file("docs/deployment.md")
    load_sequence = "\n".join((
        "set -a",
        ". ./.env",
        "set +a",
        'JOB_FILES_ROOT="${MARCEDIT_WEB_JOB_FILES_ROOT:-data/job-files}"',
    ))

    assert docs.count(load_sequence) == 2
    assert 'cp -a "$JOB_FILES_ROOT" "$BACKUP_DIR/job-files"' in docs
    assert 'rm -rf "$JOB_FILES_ROOT"' in docs
    assert '"$BACKUP_DIR/job-files" "$JOB_FILES_ROOT"' in docs
    assert "cp -a data/job-files" not in docs

    (tmp_path / ".env").write_text(
        "MARCEDIT_WEB_JOB_FILES_ROOT=/srv/custom-job-files\n"
    )
    result = subprocess.run(
        ["sh", "-c", load_sequence + "\nprintf '%s' \"$JOB_FILES_ROOT\""],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "/srv/custom-job-files"


def test_public_systemd_unit_stays_db_free():
    """The public light tier must not touch the private catalog DB."""
    unit = _repo_file("deploy/marcedit-web-public.service")

    assert "marcedit_web.ops.health" not in unit
    assert "MARCEDIT_WEB_DB_PATH" not in unit


def test_worker_systemd_unit_is_hardened_and_uses_private_data():
    """The queue worker must share private state without opening a port."""
    unit = _deploy_file("deploy/marcedit-web-worker.service")
    active = {
        line.strip()
        for line in unit.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "User=marcedit" in active
    assert "Group=marcedit" in active
    assert "WorkingDirectory=/var/www/html/marcedit-web" in active
    assert "EnvironmentFile=/var/www/html/marcedit-web/.env" in active
    assert "Environment=MARCEDIT_WEB_MODE=private" in active
    assert "Environment=MARCEDIT_WEB_PROD=1" in active
    assert (
        "Environment=MARCEDIT_WEB_DB_PATH="
        "/var/www/html/marcedit-web/data/marcedit.db"
    ) in active
    assert (
        "ExecStartPre=/var/www/html/marcedit-web/.venv/bin/python "
        "-m marcedit_web.ops.health"
    ) in active
    assert (
        "ExecStart=/var/www/html/marcedit-web/.venv/bin/python "
        "-m marcedit_web.ops.worker"
    ) in active
    assert "Restart=on-failure" in active
    assert "RestartSec=5" in active
    assert "MemoryHigh=1536M" in active
    assert "MemoryMax=2G" in active
    assert "CPUQuota=200%" in active
    assert "NoNewPrivileges=true" in active
    assert "ProtectSystem=strict" in active
    assert "ProtectHome=true" in active
    assert "PrivateTmp=true" in active
    assert "ReadWritePaths=/var/www/html/marcedit-web/data" in active
    assert not any("--server.port" in line for line in active)


def test_deploy_quiesces_worker_until_app_and_schema_are_ready():
    """Old worker code must not write while new code migrates the database."""
    script = _repo_file("scripts/deploy.sh")

    # The failure trap also stops the worker; rindex selects the actual
    # pre-update quiesce command from the rollout body.
    stop_worker = script.rindex("systemctl stop marcedit-web-worker")
    pull_code = script.index("git pull origin main")
    restart_app = script.index("systemctl restart marcedit-web-private")
    app_health = script.index("/_stcore/health")
    schema_health = script.index("-m marcedit_web.ops.health")
    start_worker = script.index("systemctl start marcedit-web-worker")
    stale_heartbeat = script.index("-m marcedit_web.ops.worker --check")
    worker_health = script.rindex("-m marcedit_web.ops.worker --check")

    assert script.count("-m marcedit_web.ops.worker --check") == 2
    assert stop_worker < stale_heartbeat < pull_code < restart_app
    assert restart_app < app_health < schema_health < start_worker < worker_health
    assert "journalctl -u marcedit-web-private -u marcedit-web-worker" in script


def test_install_and_sudoers_cover_worker_lifecycle_with_exact_commands():
    """Deployment gets only the specific root actions its rollout requires."""
    install = _repo_file("scripts/install.sh")
    sudoers = _repo_file("deploy/marcedit.sudoers")

    assert "mkdir -p data/audit data/tasks data/uploads data/operations" in install
    assert "systemctl daemon-reload" in install
    assert "systemctl enable --now marcedit-web-worker" in install
    for action in ("start", "stop", "restart"):
        assert (
            f"marcedit  ALL=(root)    NOPASSWD: /bin/systemctl {action} "
            "marcedit-web-worker"
        ) in sudoers
    assert (
        "marcedit  ALL=(root)    NOPASSWD: /bin/systemctl restart "
        "marcedit-web-private"
    ) in sudoers


def test_preflight_validates_worker_unit_storage_and_queue_settings():
    """A bad queue deployment must fail before it accepts durable work."""
    script = _repo_file("scripts/preflight-check.sh")

    assert "/etc/systemd/system/marcedit-web-worker.service" in script
    assert "MARCEDIT_WEB_OPERATIONS_ROOT" in script
    assert "MARCEDIT_WEB_QUEUE_CHUNK_RECORDS" in script
    assert "MARCEDIT_WEB_OPERATION_RETENTION_DAYS" in script
    assert "positive integer" in script
    assert "must be within $DATA_DIR" in script
    assert "mkdir" not in script


def test_deployment_docs_cover_queue_operations_and_recovery():
    """Operators need enough context to diagnose without exposing MARC data."""
    docs = _repo_file("docs/deployment.md")

    assert "journalctl -u marcedit-web-worker" in docs
    assert "python -m marcedit_web.ops.worker --check" in docs
    assert "MARCEDIT_WEB_QUEUE_CHUNK_RECORDS" in docs
    assert "MARCEDIT_WEB_OPERATION_RETENTION_DAYS" in docs
    assert "30 days" in docs
    assert "data/operations" in docs
    assert "cancell" in docs.lower()
    assert "immutable input" in docs.lower()


def test_its_setup_installs_and_operates_the_private_app_and_worker():
    """The linked one-time setup guide must not leave the durable queue idle."""
    docs = _repo_file("docs/its-setup.md")

    private_install = docs.index("deploy/marcedit-web-private.service")
    worker_install = docs.index("deploy/marcedit-web-worker.service")
    daemon_reload = docs.index("systemctl daemon-reload")
    private_enable = docs.index("systemctl enable --now marcedit-web-private")
    worker_enable = docs.index("systemctl enable --now marcedit-web-worker")

    assert private_install < worker_install < daemon_reload
    assert daemon_reload < private_enable < worker_enable
    assert "systemctl status marcedit-web-private marcedit-web-worker" in docs
    assert "python -m marcedit_web.ops.worker --check" in docs
    assert "journalctl -u marcedit-web-private" in docs
    assert "journalctl -u marcedit-web-worker" in docs
    assert "data/operations" in docs
    assert "immutable input" in docs.lower()
    assert "cancell" in docs.lower()
    assert "restarts the service via" not in docs


def test_deployment_docs_cover_published_image_worker_operations():
    """Alternate Compose operators must start and diagnose both services."""
    docs = _repo_file("docs/deployment.md")

    assert "docker-compose.pull.yml" in docs
    assert "MARCEDIT_WEB_IMAGE=" in docs
    assert "marcedit-web-worker" in docs
    assert "docker compose -f docker-compose.pull.yml up -d" in docs
    assert "docker compose -f docker-compose.pull.yml logs marcedit-web-worker" in docs
    assert "python -m marcedit_web.ops.worker --check" in docs


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
