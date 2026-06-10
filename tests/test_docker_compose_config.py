"""Tests for local Docker Compose configuration."""

from __future__ import annotations

from pathlib import Path


def test_compose_passes_gemini_key_from_environment():
    compose = Path("docker-compose.yml").read_text()

    assert "GEMINI_API_KEY=${GEMINI_API_KEY:-}" in compose
