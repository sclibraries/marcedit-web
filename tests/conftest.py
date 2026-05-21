"""Shared test fixtures for marcedit-web."""

from __future__ import annotations

import pytest
from pymarc import Field, Leader, Record, Subfield


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
