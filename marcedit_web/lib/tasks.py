"""Task registry: named transforms over MARC records.

A **task** is an atomic unit of MARC transformation — a Python function that
takes a `pymarc.Record` and mutates it in place. Tasks are decorator-
registered into the module-level `TASK_REGISTRY` so that the Tasks page
can list and run them by name.

To add a task, drop a Python file under the configured tasks directory.
`load_user_tasks()` imports those modules, and their `@task(...)`
decorators register into `TASK_REGISTRY`. A new task only needs:

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
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pymarc import Record

logger = logging.getLogger("marcedit_web.tasks")

TaskFn = Callable[["Record"], None]


@dataclass(frozen=True)
class Task:
    """One registered transform."""
    name: str
    description: str
    fn: TaskFn
    source: str  # human-readable origin (e.g. module path or filesystem path)


TASK_REGISTRY: dict[str, Task] = {}


# Track which task names each module registered. Used by `load_user_tasks`
# during the freshness-reload path: before we re-exec a changed module,
# we drop every task name it previously registered so a rename (e.g.
# `@task("foo")` → `@task("bar")`) doesn't leave the old name orphaned
# in TASK_REGISTRY with a stale function reference.
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

# Track when each user task module was last successfully loaded. A file
# whose on-disk mtime is newer than its recorded load time gets re-exec'd
# even when `force_reload=False`, so outside-the-GUI edits to a task are
# picked up the next time the cataloger triggers a run.
_MODULE_LOAD_MTIMES: dict[str, float] = {}


def load_user_tasks(tasks_dir: Path, *, force_reload: bool = False) -> int:
    """Import every .py module in `tasks_dir`, triggering `@task` registration.

    Files starting with `_` are skipped (so users can keep helper modules
    private or have an `__init__.py` without it being treated as a task
    module). Returns the count of modules **newly loaded** (already-loaded
    modules are skipped to avoid re-registering tasks on every call).

    Per-file failures are captured in `LAST_LOAD_ISSUES` as structured
    `Issue` objects (see `errors.task_load_issue`) so the CLI/GUI can
    surface actionable messages. The loop continues past failures — one
    broken task file should not hide the rest.

    Set `force_reload=True` to re-execute modules even if they're in
    `sys.modules`. This intentionally fires the "task is being re-registered"
    warning so it's not the default — use it when a user has edited a task
    file and wants the changes picked up without restarting the process.
    """
    # Local import to avoid a circular dependency at module-import time.
    from .errors import task_load_issue
    LAST_LOAD_ISSUES.clear()
    if not tasks_dir.exists():
        return 0
    loaded = 0
    for path in sorted(tasks_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"marcedit_web_user_tasks.{path.stem}"
        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            current_mtime = 0.0
        # Freshness check: if the on-disk file is newer than the last
        # successful load, re-exec the module even without explicit
        # force_reload. Outside-the-GUI edits become visible without a
        # restart, which is the whole point of the freshness check.
        stale = current_mtime > _MODULE_LOAD_MTIMES.get(mod_name, 0.0)
        if mod_name in sys.modules and not force_reload and not stale:
            continue
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            logger.warning("could not load %s — bad module spec", path)
            LAST_LOAD_ISSUES.append(task_load_issue(
                str(path), RuntimeError("bad module spec — file may be unreadable")
            ))
            continue
        # Before re-executing a module that was previously loaded, drop
        # every task name it had registered. Otherwise a rename in the
        # source (e.g. `@task("foo")` → `@task("bar")`) leaves "foo" in
        # TASK_REGISTRY pointing at the stale function — silent zombie.
        is_reload = mod_name in sys.modules
        if is_reload:
            for stale_name in _MODULE_TASK_NAMES.pop(mod_name, set()):
                TASK_REGISTRY.pop(stale_name, None)
        module = importlib.util.module_from_spec(spec)
        # Register in sys.modules so any relative imports inside the
        # module behave normally.
        sys.modules[mod_name] = module
        try:
            spec.loader.exec_module(module)
            _MODULE_LOAD_MTIMES[mod_name] = current_mtime
            loaded += 1
        except Exception as exc:  # noqa: BLE001 - we want the CLI to keep running
            logger.error("failed to load user task module %s: %s", path, exc)
            LAST_LOAD_ISSUES.append(task_load_issue(str(path), exc))
            # Don't leave a stub module in sys.modules — a later force_reload
            # would skip it under the "already loaded" guard and the user
            # wouldn't see the same error again on retry.
            sys.modules.pop(mod_name, None)
            _MODULE_LOAD_MTIMES.pop(mod_name, None)
            _MODULE_TASK_NAMES.pop(mod_name, None)
    return loaded


