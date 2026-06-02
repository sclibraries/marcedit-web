"""Tests for the Validate page's severity decoration (TASK-053).

We swapped the pandas Styler approach for an inline emoji-prefix
because Styler wrappers were breaking the ``on_select`` flow. The
prefix function is pure — input string → display string — so it
unit-tests without booting Streamlit.
"""

from __future__ import annotations

from marcedit_web.render.validate import _SEVERITY_PREFIX, _decorate_severity


def test_error_gets_red_circle():
    assert "🔴" in _decorate_severity("error")
    assert "error" in _decorate_severity("error")


def test_warning_gets_yellow_circle():
    assert "🟡" in _decorate_severity("warning")
    assert "warning" in _decorate_severity("warning")


def test_info_gets_blue_circle():
    assert "🔵" in _decorate_severity("info")
    assert "info" in _decorate_severity("info")


def test_unknown_severity_passes_through_unchanged():
    """An unexpected severity must not crash; pass-through is fine."""
    assert _decorate_severity("debug") == "debug"
    assert _decorate_severity("") == ""


def test_prefix_map_covers_all_severities_used_by_preflight():
    """Guard against a future preflight severity going undecorated."""
    expected = {"error", "warning", "info"}
    assert set(_SEVERITY_PREFIX.keys()) == expected


def test_severity_label_carries_text_not_just_color():
    """A11y: every severity label has the word too, not just the dot."""
    for sev, label in _SEVERITY_PREFIX.items():
        assert sev in label
