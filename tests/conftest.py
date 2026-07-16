"""Shared test fixtures for marcedit-web."""

from __future__ import annotations

import pytest
from pymarc import Field, Leader, Record, Subfield

from marcedit_web.lib import db as _db


@pytest.fixture(autouse=True)
def _isolated_sqlite(monkeypatch, tmp_path):
    """Point the SQLite DB + tasks root at per-test tmp paths.

    The audit module dual-writes every event to ``data/marcedit.db``
    via ``marcedit_web.lib.db``; without isolation the test suite
    would pollute the dev DB on every run. ``reset_for_tests()``
    drops the cached "initialized" flag so each test's first DB
    touch creates a fresh schema in its own tmp_path file.

    Also isolates ``MARCEDIT_WEB_TASKS_ROOT`` (TASK-050) — the
    file→SQL migration in ``init_schema`` scans this directory, and
    without the override the test DB would inherit whatever tasks
    happen to be in the developer's ``data/tasks/`` directory.
    """
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "test-suite.db"))
    monkeypatch.setenv("MARCEDIT_WEB_TASKS_ROOT", str(tmp_path / "tasks"))
    monkeypatch.setenv("MARCEDIT_WEB_UPLOADS_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv(
        "MARCEDIT_WEB_OPERATIONS_ROOT",
        str(tmp_path / "operations"),
    )
    _db.reset_for_tests()
    yield
    _db.reset_for_tests()


def _sample_record() -> Record:
    """A small synthetic record with a representative mix of fields.

    Leader is a typical online-book leader (positions 6/7 = a/m). 008 byte 23
    is 'o' so reporting can label it as an online book. Includes a 029
    (deletable junk), a 245, a 506, a 655, two 856s, and an 891.
    """
    record = Record()
    record.leader = Leader("00000nam a2200000 a 4500")
    record.add_field(Field(tag="001", data="1234567890"))
    record.add_field(Field(tag="003", data="OCoLC"))
    record.add_field(
        Field(tag="008", data="180706s2013    nyu     ob    001 0 eng d")
    )
    record.add_field(Field(tag="029", data="vendor-junk-001"))
    record.add_field(
        Field(
            tag="245",
            indicators=["1", "0"],
            subfields=[Subfield("a", "Test title.")],
        )
    )
    record.add_field(
        Field(
            tag="506",
            indicators=[" ", " "],
            subfields=[Subfield("a", "Open to all comers.")],
        )
    )
    record.add_field(
        Field(
            tag="655",
            indicators=[" ", "7"],
            subfields=[
                Subfield("a", "Electronic books."),
                Subfield("2", "local"),
            ],
        )
    )
    record.add_field(
        Field(
            tag="856",
            indicators=["4", "0"],
            subfields=[Subfield("u", "https://example.org/ebook/12345")],
        )
    )
    record.add_field(
        Field(
            tag="856",
            indicators=["4", "2"],
            subfields=[Subfield("u", "https://example.org/related/12345")],
        )
    )
    record.add_field(Field(tag="891", data="vendor-supplement"))
    return record


@pytest.fixture
def record():
    return _sample_record()


@pytest.fixture
def make_record():
    """Factory: call inside a test to get an independent record."""
    return _sample_record
