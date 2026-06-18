"""Structured diagnostics for marcedit-web.

Two complementary shapes live here:

* `Issue` — a dataclass that captures one diagnostic. Used by pre-flight
  validation, rule-driven validation, and post-transform errors. Same
  structure everywhere so the validate page, the editor's Ace
  annotations, and tests can pivot on the same fields.

* `MarcProcessError` and subclasses — exceptions that wrap one `Issue` so
  failures can travel up the call stack carrying cataloger-readable
  context. The page boundary catches `MarcProcessError`, surfaces
  `issue.message` and `issue.suggestion`, and logs the full traceback
  for developers.

The split lets internal modules `return` issues for non-fatal warnings
and `raise` issues for blocking errors, with the same payload either way.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]
Scope = Literal["file", "record", "task"]


@dataclass(frozen=True)
class Issue:
    """One structured diagnostic.

    `severity` decides whether the run is blocked (`error`), advised
    (`warning`), or informational only (`info`). `scope` tells the GUI
    where to display it. `code` is a stable string ID — tests and the
    JSON report can match against it without parsing prose.

    Optional context fields (`record_index`, `identifier`, `file_path`,
    `workflow`, `task`) are populated when they apply. They're omitted
    from `to_dict()` when None so the JSON report stays clean.
    """

    severity: Severity
    scope: Scope
    code: str            # stable identifier like "missing-001"
    message: str         # cataloger-readable summary
    suggestion: str | None = None
    record_index: int | None = None
    identifier: str | None = None
    file_path: str | None = None
    task: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict with None fields omitted."""
        return {k: v for k, v in asdict(self).items() if v is not None}


def make_record_issue(
    severity: str,
    code: str,
    message: str,
    suggestion: str | None,
    record_index: int,
    identifier: str | None,
) -> Issue:
    """Build a record-scoped Issue. Single owner shared by preflight and
    rules_validate (TASK-078c)."""
    return Issue(
        severity=severity,  # type: ignore[arg-type]
        scope="record",
        code=code,
        message=message,
        suggestion=suggestion,
        record_index=record_index,
        identifier=identifier,
    )


# ---------------------------------------------------------------------------
# Exception types
# ---------------------------------------------------------------------------


class MarcProcessError(Exception):
    """Base for all marc-process errors that carry a structured `Issue`.

    The CLI/GUI catches `MarcProcessError`, surfaces `issue.message` and
    `issue.suggestion` to the cataloger, and logs the full traceback
    (preserved on `__cause__` if you pass it through) for developers.
    """

    def __init__(self, issue: Issue, *, cause: BaseException | None = None) -> None:
        super().__init__(issue.message)
        self.issue = issue
        if cause is not None:
            self.__cause__ = cause


class TaskLoadError(MarcProcessError):
    """A user task file failed to import (syntax error, missing import, etc.)."""


class PreflightError(MarcProcessError):
    """Pre-flight detected a blocking condition (severity = error)."""


class TransformError(MarcProcessError):
    """A task raised an exception while processing a record."""


# ---------------------------------------------------------------------------
# Issue-construction helpers
# ---------------------------------------------------------------------------
#
# Common patterns get a helper so call sites stay short and the codes stay
# consistent across the codebase. Add helpers here when a new check appears
# in more than one place.


def task_load_issue(path: str, exc: BaseException) -> Issue:
    """Build a task-load failure Issue from the file path and the original
    exception. Used by `tasks.load_user_tasks` to surface syntax errors."""
    return Issue(
        severity="error",
        scope="task",
        code="task-load-failed",
        message=f"could not load task file {path}: {type(exc).__name__}: {exc}",
        suggestion=(
            "open the task in Code view, fix the syntax error, then save again"
        ),
        file_path=path,
    )


def transform_issue(
    record_index: int,
    identifier: str | None,
    task_name: str | None,
    exc: BaseException,
) -> Issue:
    """Build a per-record transform failure Issue from the task runner."""
    return Issue(
        severity="error",
        scope="record",
        code="transform-failed",
        message=f"{type(exc).__name__}: {exc}",
        suggestion=(
            "review the failing record in the viewer; if a task threw the "
            "exception, open it in Code view and check the logic"
        ),
        record_index=record_index,
        identifier=identifier,
        task=task_name,
    )
