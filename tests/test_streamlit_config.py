"""TASK-175: viewer-safe Streamlit activity chrome contract."""

from pathlib import Path


def test_streamlit_uses_viewer_toolbar_for_activity_feedback():
    config = Path(".streamlit/config.toml").read_text(encoding="utf-8")

    assert "toolbarMode = \"viewer\"" in config
    assert "toolbarMode = \"minimal\"" not in config

