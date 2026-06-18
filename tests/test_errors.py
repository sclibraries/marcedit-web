"""Tests for marcedit_web.lib.errors."""

from __future__ import annotations

import pytest

from marcedit_web.lib.errors import (
    Issue,
    MarcProcessError,
    PreflightError,
    TaskLoadError,
    TransformError,
    make_record_issue,
    task_load_issue,
    transform_issue,
)


def test_issue_to_dict_omits_none():
    issue = Issue(
        severity="error",
        scope="record",
        code="missing-001",
        message="no 001",
        record_index=3,
    )
    d = issue.to_dict()
    assert d["severity"] == "error"
    assert d["record_index"] == 3
    assert "suggestion" not in d
    assert "task" not in d


def test_task_load_issue_carries_path_and_exc():
    issue = task_load_issue("/tmp/tasks/foo.py", SyntaxError("bad"))
    assert issue.severity == "error"
    assert issue.scope == "task"
    assert issue.code == "task-load-failed"
    assert "foo.py" in issue.message
    assert "SyntaxError" in issue.message


def test_transform_issue_uses_task_field():
    issue = transform_issue(7, "abc123", "my-task", ValueError("nope"))
    assert issue.severity == "error"
    assert issue.scope == "record"
    assert issue.code == "transform-failed"
    assert issue.record_index == 7
    assert issue.identifier == "abc123"
    assert issue.task == "my-task"


def test_marc_process_error_wraps_issue():
    issue = Issue(severity="error", scope="file", code="x", message="boom")
    exc = MarcProcessError(issue)
    assert exc.issue is issue
    assert str(exc) == "boom"


def test_dropped_exception_classes_are_gone():
    """Workflow + Registry validation errors were Smith-specific; must be gone."""
    from marcedit_web.lib import errors

    assert not hasattr(errors, "WorkflowValidationError")
    assert not hasattr(errors, "RegistryValidationError")
    assert not hasattr(errors, "workflow_validation_issue")


def test_specific_exceptions_subclass_marc_process_error():
    issue = Issue(severity="error", scope="file", code="x", message="m")
    for cls in (TaskLoadError, PreflightError, TransformError):
        assert issubclass(cls, MarcProcessError)
        exc = cls(issue)
        assert exc.issue is issue


def test_issue_scope_drops_workflow_and_registry():
    """Type-level: scope literal no longer accepts dropped Smith values.

    We can't enforce a Literal at runtime, but the field shouldn't accept
    non-listed strings via mypy. We at least verify the kept ones.
    """
    for scope in ("file", "record", "task"):
        Issue(severity="info", scope=scope, code="x", message="m")


def test_make_record_issue_builds_record_scoped_issue():
    """TASK-078c: the single record-issue factory shared by preflight + rules_validate."""
    issue = make_record_issue(
        "warning", "duplicate-001", "two records share 001", "dedupe", 4, "ocm123"
    )
    assert issue.severity == "warning"
    assert issue.scope == "record"
    assert issue.code == "duplicate-001"
    assert issue.message == "two records share 001"
    assert issue.suggestion == "dedupe"
    assert issue.record_index == 4
    assert issue.identifier == "ocm123"
