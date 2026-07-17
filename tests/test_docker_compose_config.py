"""Tests for local Docker Compose + image build configuration."""

from __future__ import annotations

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
