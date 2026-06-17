"""Regression guard: every MARC blob marcedit-web emits must DECLARE UTF-8.

This is NOT a bug fix. pymarc 5.x already does the right thing: ``Record.as_marc``
sets leader/09 to ``'a'`` (and encodes UTF-8) for any record whose ``to_unicode``
flag is set. Every read path in this app reads with ``to_unicode=True`` — whether
via ``MARCReader(to_unicode=True)`` or a bare ``pymarc.Record(data=...)``, which
defaults ``to_unicode=True``. ``MARCWriter.write`` calls ``as_marc``, so all write
sinks inherit that behavior.

These tests PIN that behavior so it cannot silently regress, because the catalog
depends on it: a blob that declares MARC-8 (leader/09 == ' ') while carrying
UTF-8 bytes is mojibake to downstream systems. Two realistic ways it could
regress, both of which these tests would catch:

* a future pymarc bump past the current ``pymarc>=5.1.2,<6`` pin that changes the
  ``as_marc`` coding-scheme logic, or
* an accidental ``to_unicode=False`` introduced on a read path.

Coverage spans the real emit sinks: the RecordStore download (``to_mrc_bytes``)
and streaming (``write_mrc_to``) paths, the Tasks-run output path
(``from_records``), and the converters ``.mrk`` -> ``.mrc`` export. The MARCXML
export (``to_binary_from_marcxml``) routes through the same ``_write_binary`` the
mrk test exercises, so it shares the guarded invariant.

See TASK-070 (the audit's claimed leader/09 corruption bug, which does not exist
on the supported dependency range — these guards keep it that way).
"""

from __future__ import annotations

import io

import pymarc

from marcedit_web.lib import converters
from marcedit_web.lib.record_store import RecordStore


def _leader09(blob: bytes) -> str:
    """Coding-scheme byte: ' ' declares MARC-8, 'a' declares UTF-8."""
    return blob[9:10].decode("latin1")


def _marc8_declared_record(value: str = "Guard test title") -> bytes:
    """One binary MARC record whose leader DECLARES MARC-8 (leader/09 == ' ').

    Built by serializing a record (pymarc emits leader/09 == 'a') and patching
    the coding-scheme byte back to a space to simulate a legacy MARC-8 input
    file. ASCII data is used so the MARC-8 reinterpretation on read is a no-op
    and the test isolates the leader-declaration invariant from data fidelity
    (genuine MARC-8 charset transcoding is out of scope for a declaration guard).
    """
    rec = pymarc.Record()
    rec.add_field(
        pymarc.Field(
            tag="245",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield(code="a", value=value)],
        )
    )
    raw = bytearray(rec.as_marc())
    raw[9] = ord(" ")  # declare MARC-8
    return bytes(raw)


def test_marc8_declared_input_is_emitted_as_utf8_by_record_store(tmp_path):
    """RecordStore.to_mrc_bytes (the .mrc download path) up-declares MARC-8 -> UTF-8."""
    src = _marc8_declared_record()
    assert _leader09(src) == " "  # precondition: input genuinely declares MARC-8

    store = RecordStore.from_bytes(
        src, tmp_dir=tmp_path / "rs", filename="legacy.mrc"
    )
    out = store.to_mrc_bytes()

    assert _leader09(out) == "a"  # invariant: emitted blob declares UTF-8
    rec = next(pymarc.MARCReader(io.BytesIO(out), to_unicode=True, permissive=True))
    assert rec["245"]["a"] == "Guard test title"  # data survives the round trip


def test_marc8_declared_input_is_emitted_as_utf8_by_write_mrc_to(tmp_path):
    """RecordStore.write_mrc_to (the streaming sink used by Tasks/Dedupe) up-declares."""
    src = _marc8_declared_record()
    assert _leader09(src) == " "

    store = RecordStore.from_bytes(src, tmp_dir=tmp_path / "rs", filename="legacy.mrc")
    out_path = tmp_path / "out.mrc"
    store.write_mrc_to(out_path)

    assert _leader09(out_path.read_bytes()) == "a"


def test_record_store_from_records_emits_utf8_declared(tmp_path):
    """The Tasks-run output path (from_records) declares UTF-8."""
    rec = pymarc.Record()
    rec.add_field(
        pymarc.Field(
            tag="245",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield(code="a", value="Plain title")],
        )
    )
    store = RecordStore.from_records([rec], tmp_dir=tmp_path / "fr")

    assert _leader09(store.to_mrc_bytes()) == "a"


def test_marc8_declared_input_up_declares_through_mrk_export():
    """converters .mrc -> .mrk -> .mrc must up-declare a MARC-8 input to UTF-8.

    Starts from a MARC-8-declared blob (not an already-UTF-8 one) so that a
    ``to_unicode=False`` regression in the write step would leave the output
    declaring MARC-8 and fail this test.
    """
    src = _marc8_declared_record()
    assert _leader09(src) == " "  # precondition: round trip starts from MARC-8

    mrk = converters.to_mrk_text(src)
    out = converters.to_binary_from_mrk(mrk.output)

    assert isinstance(out.output, bytes)
    assert _leader09(out.output) == "a"


def test_mrk_export_preserves_non_ascii_data_and_declares_utf8():
    """The .mrk export round-trips diacritics intact and declares UTF-8."""
    rec = pymarc.Record()
    rec.add_field(
        pymarc.Field(
            tag="245",
            indicators=[" ", " "],
            subfields=[pymarc.Subfield(code="a", value="Café résumé")],
        )
    )
    mrk = converters.to_mrk_text(rec.as_marc())
    out = converters.to_binary_from_mrk(mrk.output)

    assert _leader09(out.output) == "a"
    back = next(
        pymarc.MARCReader(io.BytesIO(out.output), to_unicode=True, permissive=True)
    )
    assert back["245"]["a"] == "Café résumé"
