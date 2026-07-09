"""Tests for Tasks-page export naming (TASK-141)."""

from __future__ import annotations

import re
import sys
from types import SimpleNamespace


def _tasks_render():
    sys.modules.setdefault(
        "streamlit_ace",
        SimpleNamespace(st_ace=lambda *args, **kwargs: None),
    )
    from marcedit_web.render import tasks as tasks_render

    return tasks_render


def test_export_filename_keeps_source_name_but_adds_operation_suffix():
    tasks_render = _tasks_render()

    filename = tasks_render._export_filename("source-file.mrc", "tasks")

    assert filename != "source-file.mrc"
    assert re.fullmatch(r"source-file_tasks_\d{8}_\d{6}\.mrc", filename)


def test_export_filename_defaults_when_source_missing():
    tasks_render = _tasks_render()

    filename = tasks_render._export_filename(None, "quickbatch")

    assert re.fullmatch(r"transformed_quickbatch_\d{8}_\d{6}\.mrc", filename)


def test_history_location_caption_points_to_job_snapshots_when_available():
    tasks_render = _tasks_render()

    assert tasks_render._history_location_caption(7) == (
        "Rollback and before/after downloads are available under Job snapshots "
        "on this Tasks page."
    )


def test_history_location_caption_explains_unsigned_fallback():
    tasks_render = _tasks_render()

    assert tasks_render._history_location_caption(None) == (
        "Rollback history is only available for signed-in job files. "
        "Download the updated MARC file below."
    )
