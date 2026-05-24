"""Filesystem layout for user-built and shared tasks.

v1 stored tasks in a ``tempfile.mkdtemp(...)`` per session, which lost
catalogers' work between visits. v2 stores them under ``data/tasks/``
on the configured `MARCEDIT_WEB_TASKS_ROOT` filesystem (defaulting to
the project's ``data/tasks/``).

Layout::

    data/tasks/
        users/
            <safe-user>/    # one dir per cataloger (eppn-based when
                            # Shibboleth is wired; "anonymous" in dev)
                *.py        # one task per file (`@task(...)`-decorated)
        shared/
            *.py            # tasks anyone on the box can load

Load order: ``shared/`` first, then the user dir. ``tasks.load_user_tasks``
already handles the freshness reload semantics, so a same-name task in
the user dir naturally overrides the shared one — the second load
re-registers the function in ``TASK_REGISTRY``.

Slug safety: the user identifier (often a Shibboleth eppn like
``user@example.edu``) is normalized via :func:`safe_user_slug` before
being used as a path segment. Only ``[A-Za-z0-9_.@-]`` survive; every
other char (including ``/`` and ``..``) maps to ``_`` so a malicious
inbound header can't escape ``data/tasks/users/``.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("marcedit_web.task_storage")

_DEFAULT_TASKS_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "tasks"
_SLUG_RE = re.compile(r"[^A-Za-z0-9_.@-]")


def tasks_root() -> Path:
    """Return the configured tasks root.

    Reads ``MARCEDIT_WEB_TASKS_ROOT`` from the environment so tests
    (and future per-environment configuration) can point this anywhere.
    """
    override = os.environ.get("MARCEDIT_WEB_TASKS_ROOT")
    if override:
        return Path(override)
    return _DEFAULT_TASKS_ROOT


def safe_user_slug(user: str) -> str:
    """Sanitize a user identifier into a filesystem-safe slug.

    ``safe_user_slug("rconnell@smith.edu")`` → ``"rconnell@smith.edu"``.
    ``safe_user_slug("../../etc/passwd")`` → ``"___etc_passwd"`` (no
    ``..`` runs remain). Empty / falsy → ``"anonymous"`` so we always
    have a stable dir.
    """
    if not user:
        return "anonymous"
    # Pass 1: collapse anything outside the whitelist to underscores.
    slug = _SLUG_RE.sub("_", user)
    # Pass 2: kill any `..` runs — `.` is allowed (emails use it) but
    # `..` is parent-dir traversal. Replace each `.` in a run with `_`
    # until no `..` survives.
    while ".." in slug:
        slug = slug.replace("..", "_.")
    slug = slug.strip("_.")
    return slug or "anonymous"


def user_tasks_dir(user: str) -> Path:
    """Per-user tasks dir. Created lazily on first save / load."""
    root = tasks_root()
    path = root / "users" / safe_user_slug(user)
    path.mkdir(parents=True, exist_ok=True)
    return path


def shared_tasks_dir() -> Path:
    """Shared task library readable by all users."""
    path = tasks_root() / "shared"
    path.mkdir(parents=True, exist_ok=True)
    return path


def visible_task_dirs(user: str) -> list[Path]:
    """Return dirs to load tasks from for ``user``.

    Order: shared first, user second. A user-named task shadows a
    shared one because the loader re-registers the function under
    the same task name on the second pass.
    """
    return [shared_tasks_dir(), user_tasks_dir(user)]
