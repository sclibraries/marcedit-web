"""Tests for local Docker Compose + image build configuration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_compose_passes_gemini_key_from_environment():
    compose = Path("docker-compose.yml").read_text()

    assert "GEMINI_API_KEY=${GEMINI_API_KEY:-}" in compose


def test_compose_mounts_large_batch_benchmark_read_only():
    """Docker tests need the benchmark without exposing all host scripts."""
    compose = Path("docker-compose.yml").read_text()

    assert (
        "- ./scripts/benchmark-large-batch.py:"
        "/app/scripts/benchmark-large-batch.py:ro"
    ) in compose


def test_compose_worker_shares_private_configuration_without_a_port():
    """The worker needs app state and settings, never network exposure."""
    compose = Path("docker-compose.yml").read_text()
    marker = "  marcedit-web-worker:"

    assert marker in compose
    worker = compose.split(marker, 1)[1]
    assert "build: ." in worker
    assert "image: marcedit-web:dev" in worker
    assert "container_name:" not in worker
    assert "ports:" not in worker
    assert "- ./marcedit_web:/app/marcedit_web:ro" in worker
    assert "- ./data:/app/data" in worker
    assert "- ./.streamlit:/app/.streamlit:ro" in worker
    assert "PYTHONUNBUFFERED=1" in worker
    assert "MARCEDIT_WEB_PROXY_SECRET=${MARCEDIT_WEB_PROXY_SECRET:-}" in worker
    assert "GEMINI_API_KEY=${GEMINI_API_KEY:-}" in worker
    assert "python -m marcedit_web.ops.worker" in worker
    assert "condition: service_healthy" in worker
    assert "restart: unless-stopped" in worker


@pytest.mark.parametrize("compose_name", ["docker-compose.yml", "docker-compose.pull.yml"])
def test_compose_sets_bounded_operation_download_default(compose_name):
    compose = _build_context_file(compose_name)

    assert "MARCEDIT_WEB_OPERATION_DOWNLOAD_MAX_BYTES" in compose
    assert "209715200" in compose


def test_pull_compose_worker_uses_published_image_and_shared_private_state():
    """Published-image installs need the queue worker without another port."""
    compose = _build_context_file("docker-compose.pull.yml")
    marker = "  marcedit-web-worker:"

    assert marker in compose
    worker = compose.split(marker, 1)[1]
    assert (
        "image: ${MARCEDIT_WEB_IMAGE:?Set MARCEDIT_WEB_IMAGE to a published image"
        in worker
    )
    assert "pull_policy: always" in worker
    assert "container_name:" not in worker
    assert "ports:" not in worker
    assert "${MARCEDIT_WEB_DATA_DIR:-./data}:/app/data" in worker
    assert 'PYTHONUNBUFFERED: "1"' in worker
    assert 'MARCEDIT_WEB_DB_PATH: "/app/data/marcedit.db"' in worker
    assert "${MARCEDIT_WEB_DB_PATH" not in worker
    assert 'MARCEDIT_WEB_PROXY_SECRET: "${MARCEDIT_WEB_PROXY_SECRET:-}"' in worker
    assert "python -m marcedit_web.ops.worker" in worker
    assert "condition: service_healthy" in worker
    assert "restart: unless-stopped" in worker


def test_pull_compose_app_image_supplies_dependency_healthcheck():
    """Worker startup ordering relies on the published image's real DB probe."""
    compose = _build_context_file("docker-compose.pull.yml")
    dockerfile = _build_context_file("Dockerfile")

    assert "condition: service_healthy" in compose
    assert "HEALTHCHECK" in dockerfile
    assert "python -m marcedit_web.ops.health" in dockerfile
    assert "_stcore/health" in dockerfile


@pytest.mark.parametrize("compose_name", ["docker-compose.yml", "docker-compose.pull.yml"])
def test_compose_rendering_isolates_container_paths_from_native_env(
    compose_name, tmp_path
):
    """A native .env must never point containers at unmounted host paths."""
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is required to render Compose configuration")
    source = _build_context_file(compose_name)
    (tmp_path / compose_name).write_text(source)
    (tmp_path / ".env").write_text(
        "MARCEDIT_WEB_IMAGE=example.invalid/marcedit-web:test\n"
        "MARCEDIT_WEB_DB_PATH=/var/www/html/marcedit-web/data/native.db\n"
        "MARCEDIT_WEB_OPERATIONS_ROOT=/var/www/html/marcedit-web/data/native-ops\n"
        "MARCEDIT_WEB_AUDIT_DIR=/var/www/html/marcedit-web/data/native-audit\n"
        "MARCEDIT_WEB_JOB_FILES_ROOT=/var/www/html/marcedit-web/data/native-jobs\n"
        "MARCEDIT_WEB_TASKS_ROOT=/var/www/html/marcedit-web/data/native-tasks\n"
        "MARCEDIT_WEB_UPLOADS_ROOT=/var/www/html/marcedit-web/data/native-uploads\n"
    )
    env = os.environ.copy()
    env["MARCEDIT_WEB_IMAGE"] = "example.invalid/marcedit-web:test"
    env.update(
        {
            key: f"/var/www/html/marcedit-web/data/native-{key.lower()}"
            for key in (
                "MARCEDIT_WEB_DB_PATH",
                "MARCEDIT_WEB_OPERATIONS_ROOT",
                "MARCEDIT_WEB_AUDIT_DIR",
                "MARCEDIT_WEB_JOB_FILES_ROOT",
                "MARCEDIT_WEB_TASKS_ROOT",
                "MARCEDIT_WEB_UPLOADS_ROOT",
            )
        }
    )
    result = subprocess.run(
        ["docker", "compose", "-f", compose_name, "config", "--format", "json"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(result.stdout)["services"]
    expected = {
        "MARCEDIT_WEB_DB_PATH": "/app/data/marcedit.db",
        "MARCEDIT_WEB_OPERATIONS_ROOT": "/app/data/operations",
        "MARCEDIT_WEB_AUDIT_DIR": "/app/data/audit",
        "MARCEDIT_WEB_JOB_FILES_ROOT": "/app/data/job-files",
        "MARCEDIT_WEB_TASKS_ROOT": "/app/data/tasks",
        "MARCEDIT_WEB_UPLOADS_ROOT": "/app/data/uploads",
    }
    for service_name in ("marcedit-web", "marcedit-web-worker"):
        service = services[service_name]
        assert {
            key: service["environment"][key] for key in expected
        } == expected
        assert any(
            volume["target"] == "/app/data" for volume in service["volumes"]
        )


# --- TASK-069: secrets must never be baked into the image -------------------
#
# These read build-context files (Dockerfile/.dockerignore) that exist on the
# host and in CI (which checks out the repo) but are NOT mounted into the
# runtime container, so they skip there rather than fail.


def _build_context_file(name: str) -> str:
    p = Path(name)
    if not p.exists():
        pytest.skip(f"{name} not in build context (running inside the built image)")
    return p.read_text()


def test_dockerignore_excludes_streamlit_secrets():
    """secrets.toml must be excluded from the Docker build context so it can
    never be copied into an image even by a broad COPY. (TASK-069)"""
    content = _build_context_file(".dockerignore")
    assert ".streamlit/secrets.toml" in content


def test_dockerfile_does_not_bake_streamlit_secrets():
    """The Dockerfile must copy only non-secret config, not the whole
    `.streamlit` dir (which would bake `secrets.toml` into the image). Secrets
    are provided at runtime via mount/env instead. (TASK-069)"""
    content = _build_context_file("Dockerfile")
    assert "COPY .streamlit ./.streamlit" not in content
    assert "COPY .streamlit/config.toml ./.streamlit/config.toml" in content


def test_docker_healthcheck_requires_db_readiness():
    """TASK-084: container health must check DB readiness, not only Streamlit."""
    content = _build_context_file("Dockerfile")
    assert "python -m marcedit_web.ops.health" in content
    assert "_stcore/health" in content


def test_docker_image_includes_canonical_jobs_help():
    """Private Docker deployments must have the same guide as source."""
    content = _build_context_file("Dockerfile")

    assert "COPY docs/jobs.md ./docs/jobs.md" in content


def test_docker_build_context_includes_only_canonical_jobs_help():
    """The guide must enter the image without including unrelated docs."""
    patterns = _build_context_file(".dockerignore").splitlines()

    assert "docs/*" in patterns
    assert "!docs/jobs.md" in patterns
