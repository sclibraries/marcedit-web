"""Task registry: named transforms over MARC records.

A **task** is an atomic unit of MARC transformation — a Python function
body that takes a `pymarc.Record` and mutates it in place.

Two registration paths:

* **In-tree built-ins**: the legacy ``@task(...)`` decorator runs at
  Python import time and writes a fully-callable :class:`Task` (with a
  live ``fn``) into ``TASK_REGISTRY``. Used for tasks that ship with
  the package and are imported by the test suite.
* **User task files**: ``load_user_tasks(tasks_dir)`` discovers
  ``tasks/*.py`` files via :func:`editor.parse_user_task_file`, which
  reads each file with ``ast.parse`` and **never executes** module-
  level statements. The registered :class:`Task` carries name +
  description + source path; ``fn`` is ``None`` because the body runs
  inside the subprocess sandbox at run time, not in this process. See
  TASK-029 (security review High 2) for rationale.

A user-authored task file still looks the same — drop a Python file
under the configured tasks directory:

    from marcedit_web.lib.tasks import task

    @task("strip-oclc-license-856",
          description="Remove OCLC metadata license 856 URLs.")
    def strip_oclc_license(record):
        keep = [
            f for f in record.get_fields("856")
            if not any("oclc.org/content/dam" in (sf.value or "")
                       for sf in f.subfields)
        ]
        record.remove_fields("856")
        for f in keep:
            record.add_ordered_field(f)

`load_user_tasks` lifts the name + description out of the decorator
AST node; the function body is read and shipped to the sandbox via
:func:`editor.parse_user_task_file` again from the run path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pymarc import Record

logger = logging.getLogger("marcedit_web.tasks")

TaskFn = Callable[["Record"], None]


@dataclass(frozen=True)
class Task:
    """One registered transform.

    ``fn`` is set when the task was registered via the ``@task(...)``
    decorator during in-process import (the legacy path, retained for
    in-tree built-in tasks). User tasks loaded via the AST-only
    discovery path (TASK-029 / High 2) leave ``fn=None`` — execution
    goes through the subprocess sandbox via the saved body text, so
    no callable is needed.
    """
    name: str
    description: str
    fn: Optional[TaskFn]
    source: str  # human-readable origin (e.g. module path or filesystem path)


TASK_REGISTRY: dict[str, Task] = {}


# Track which task names each file registered. Used by `load_user_tasks`
# during the freshness-reload path: before we re-parse a changed file we
# drop every task name it previously registered, so a rename (e.g.
# `@task("foo")` → `@task("bar")`) doesn't leave the old name orphaned
# in TASK_REGISTRY pointing at the stale source path.
_MODULE_TASK_NAMES: dict[str, set[str]] = {}


def task(name: str, *, description: str = "") -> Callable[[TaskFn], TaskFn]:
    """Decorator: register `fn` as a task callable by `name`."""
    def decorator(fn: TaskFn) -> TaskFn:
        source = getattr(fn, "__module__", "<unknown>")
        if name in TASK_REGISTRY and TASK_REGISTRY[name].fn is not fn:
            logger.warning(
                "task %r is being re-registered (was %s, now %s)",
                name, TASK_REGISTRY[name].source, source,
            )
        TASK_REGISTRY[name] = Task(
            name=name, description=description, fn=fn, source=source
        )
        _MODULE_TASK_NAMES.setdefault(source, set()).add(name)
        return fn
    return decorator


def get(name: str) -> Task | None:
    """Look up a task by name. Returns None if it isn't registered."""
    return TASK_REGISTRY.get(name)


def all_tasks() -> list[Task]:
    """Return all registered tasks, sorted by name."""
    return sorted(TASK_REGISTRY.values(), key=lambda t: t.name)


# Issues collected from the most recent `load_user_tasks()` call. The CLI/GUI
# read this to surface task-load failures to the cataloger after auto-loading.
# A list rather than per-call return because `load_user_tasks` is called from
# multiple places (engine, GUI, install_pipelines) and we want the latest run's
# failures to be the canonical record.
LAST_LOAD_ISSUES: list = []

# Track when each user task file was last successfully parsed. A file
# whose on-disk mtime is newer than its recorded load time gets re-parsed
# even when `force_reload=False`, so outside-the-GUI edits to a task are
# picked up the next time the cataloger triggers a run.
_MODULE_LOAD_MTIMES: dict[str, float] = {}


def load_user_tasks(tasks_dir: Path, *, force_reload: bool = False) -> int:
    """Discover user task files via AST parsing — never exec the modules.

    User task files are arbitrary Python that the cataloger (or the
    MarcEdit importer, or a sandboxed task that escapes its workdir)
    might author. Running ``spec.loader.exec_module(module)`` here, as
    the v1/v2 path did, would execute every module-level statement in
    the parent Streamlit process — outside the subprocess sandbox.
    TASK-029 (security review High 2) closed that gap by switching
    discovery to ``editor.parse_user_task_file``, which only does
    ``ast.parse`` + AST node walks. The actual task body still ships
    to the sandbox at run time via ``editor.parse_user_task_file``
    again from the run path.

    Files starting with ``_`` are skipped (helper modules, __init__).
    Returns the count of files **newly registered** in this call.
    Per-file failures land in ``LAST_LOAD_ISSUES``; the loop continues
    past failures so one broken file doesn't hide the rest.

    The ``force_reload`` flag re-reads every task file from disk, even
    those whose mtime hasn't changed. Used when the cataloger has
    just saved an edit and wants the rest of the page to see it.
    """
    # Local import to avoid a circular dependency at module-import time.
    from . import editor
    from .errors import task_load_issue
    LAST_LOAD_ISSUES.clear()
    if not tasks_dir.exists():
        return 0
    loaded = 0
    for path in sorted(tasks_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        # Module-name slot kept stable so the freshness map +
        # task-name tracking still keys on it; nothing ever exec'd.
        mod_name = f"marcedit_web_user_tasks.{path.stem}"
        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            current_mtime = 0.0
        stale = current_mtime > _MODULE_LOAD_MTIMES.get(mod_name, 0.0)
        if mod_name in _MODULE_LOAD_MTIMES and not force_reload and not stale:
            continue
        # On reload, drop names this file previously registered so a
        # renamed task doesn't leave a zombie entry in the registry.
        for stale_name in _MODULE_TASK_NAMES.pop(mod_name, set()):
            TASK_REGISTRY.pop(stale_name, None)
        try:
            parsed = editor.parse_user_task_file(path)
        except ValueError as exc:
            logger.error("failed to parse user task file %s: %s", path, exc)
            LAST_LOAD_ISSUES.append(task_load_issue(str(path), exc))
            _MODULE_LOAD_MTIMES.pop(mod_name, None)
            continue
        name = parsed["name"]
        description = parsed["description"]
        if name in TASK_REGISTRY and TASK_REGISTRY[name].source != str(path):
            logger.warning(
                "task %r is being re-registered (was %s, now %s)",
                name, TASK_REGISTRY[name].source, path,
            )
        TASK_REGISTRY[name] = Task(
            name=name, description=description, fn=None, source=str(path),
        )
        _MODULE_TASK_NAMES.setdefault(mod_name, set()).add(name)
        _MODULE_LOAD_MTIMES[mod_name] = current_mtime
        loaded += 1
    return loaded


