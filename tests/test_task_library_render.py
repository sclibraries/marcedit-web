"""Pure task-library explorer helpers (TASK-193)."""

import sys
from types import SimpleNamespace

sys.modules.setdefault(
    "streamlit_ace",
    SimpleNamespace(st_ace=lambda *args, **kwargs: None),
)

from marcedit_web.render import tasks as tasks_render


def _folders():
    return [
        {
            "id": 1,
            "scope": "personal",
            "owner_email": "alice@example.edu",
            "parent_id": None,
            "name": "Unfiled",
            "task_ids": [],
        },
        {
            "id": 2,
            "scope": "personal",
            "owner_email": "alice@example.edu",
            "parent_id": 1,
            "name": "zeta",
            "task_ids": [],
        },
        {
            "id": 3,
            "scope": "personal",
            "owner_email": "alice@example.edu",
            "parent_id": 2,
            "name": "Alpha",
            "task_ids": [7],
        },
        {
            "id": 4,
            "scope": "shared",
            "owner_email": None,
            "parent_id": None,
            "name": "Unfiled",
            "task_ids": [],
        },
    ]


def test_folder_helpers_sort_scope_tree_and_compute_paths():
    folders = _folders()

    assert [row["id"] for row in tasks_render._folder_children(
        folders, scope="personal", parent_id=1
    )] == [2]
    assert tasks_render._folder_descendants(folders, 1) == {2, 3}
    assert tasks_render._folder_path_map(folders)[3] == (
        "My Tasks / Unfiled / zeta / Alpha"
    )


def test_folder_descendant_cycle_is_bounded():
    folders = _folders()
    folders[1]["parent_id"] = 3

    assert tasks_render._folder_descendants(folders, 2) == {2, 3}
