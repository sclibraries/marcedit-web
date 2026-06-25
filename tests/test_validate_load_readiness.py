"""Validate-page integration for load-readiness warnings."""

from __future__ import annotations

from marcedit_web.lib.rules import RuleSet
from marcedit_web.render import validate


class _FakeStatus:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, **_kwargs):
        return None


class _FakeStore:
    def __init__(self, records):
        self._records = records

    def iter_records(self):
        return iter(self._records)


def test_validate_compute_issues_includes_load_readiness_warnings(
    make_record,
    monkeypatch,
):
    """Validate should show FOLIO/EDS CC readiness warnings in its issue table."""
    monkeypatch.setattr(validate.st, "status", lambda *_args, **_kwargs: _FakeStatus())
    store = _FakeStore([make_record()])

    issues = validate._compute_issues(RuleSet(), store, malformed=0)
    codes = {issue.code for issue in issues}

    assert "load-missing-006" in codes
    assert "load-missing-007" in codes
