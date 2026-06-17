"""Path-traversal guard for the MarcEdit ``.task`` archive import (TASK-071).

The importer wrote the uploaded archive to a scratch file whose name was built
directly from the client-supplied upload filename
(``tasks_dir / f".__import__{upl.name}"``). A filename containing ``../`` (sent
via curl / an intercepting proxy — the Streamlit type filter is client-side
only) escaped ``tasks_dir`` and let any authenticated user write+delete an
arbitrary ``.task``-suffixed path. These tests pin that the scratch file is
always a direct child of ``tasks_dir`` and is always cleaned up.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from marcedit_web.lib import marcedit_import
from marcedit_web.render import tasks as render_tasks


MALICIOUS_NAMES = [
    "../../../../etc/cron.d/evil.task",
    "/etc/passwd.task",
    "x/../../../../tmp/y.task",
    "..",
    "subdir/evil.task",
    "with\x00null.task",
]


@pytest.mark.parametrize("name", MALICIOUS_NAMES)
def test_archive_scratch_path_never_escapes_tasks_dir(tmp_path, name):
    """The client filename must never move the scratch file out of tasks_dir."""
    p = render_tasks._archive_scratch_path(tmp_path, name)
    assert p.parent == tmp_path
    assert p.resolve().is_relative_to(tmp_path.resolve())


def test_archive_scratch_path_is_unique_per_call(tmp_path):
    """Concurrent imports of like-named files must not collide on the scratch path."""
    a = render_tasks._archive_scratch_path(tmp_path, "same.task")
    b = render_tasks._archive_scratch_path(tmp_path, "same.task")
    assert a != b


def test_convert_uploaded_archive_writes_inside_tasks_dir_and_cleans_up(
    tmp_path, monkeypatch
):
    """Even a traversal filename keeps the actual write inside tasks_dir, and the
    scratch file is removed afterward."""
    seen = {}

    def fake_convert(path):
        path = Path(path)
        seen["path"] = path
        seen["existed_during_convert"] = path.exists()
        return SimpleNamespace(archive_errors=[], entries=[])

    monkeypatch.setattr(marcedit_import, "convert_task_archive", fake_convert)

    result = render_tasks._convert_uploaded_archive(
        tmp_path, "../../../../etc/cron.d/evil.task", b"not-a-real-zip"
    )

    assert seen["existed_during_convert"] is True
    assert seen["path"].parent == tmp_path            # never escaped via filename
    assert not seen["path"].exists()                  # cleaned up on success
    assert not (tmp_path.parent / "etc").exists()     # nothing leaked outside
    assert result.entries == []


def test_convert_uploaded_archive_cleans_up_on_error(tmp_path, monkeypatch):
    """The scratch file is removed even if conversion raises (try/finally)."""
    seen = {}

    def boom(path):
        seen["path"] = Path(path)
        assert seen["path"].exists()  # written before convert is called
        raise RuntimeError("convert exploded")

    monkeypatch.setattr(marcedit_import, "convert_task_archive", boom)

    with pytest.raises(RuntimeError):
        render_tasks._convert_uploaded_archive(tmp_path, "name.task", b"x")

    assert not seen["path"].exists()  # try/finally removed it


def test_convert_uploaded_archive_happy_path_real_zip(tmp_path):
    """End-to-end through the real converter: a valid .task zip still imports,
    and the scratch file is cleaned up afterward."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("solo.txt", "SORTBY\n")

    result = render_tasks._convert_uploaded_archive(
        tmp_path, "anything.task", buf.getvalue()
    )

    assert result.archive_errors == []
    assert len(result.entries) == 1
    assert result.entries[0].success
    assert not any(p.name.startswith(".__import__") for p in tmp_path.iterdir())
