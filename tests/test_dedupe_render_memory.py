"""Bounded-memory helpers for the Dedupe renderer (TASK-147)."""

from __future__ import annotations

import mmap

import pymarc

from marcedit_web.lib.dedupe_strategy import KeeperStrategy, StrategyParams
from marcedit_web.render import dedupe


def _record(control_number: str) -> pymarc.Record:
    record = pymarc.Record()
    record.leader = pymarc.Leader("00000nam a2200000 a 4500")
    record.add_field(pymarc.Field(tag="001", data=control_number))
    return record


def test_apply_strategy_from_path_passes_mmap_without_whole_file_copy(
    monkeypatch, tmp_path
):
    source_path = tmp_path / "batch.mrc"
    source_path.write_bytes(_record("one").as_marc())
    seen = []

    def _apply(groups, source, strategy, params):
        seen.append(source)
        assert isinstance(source, mmap.mmap)
        return {"group": 0}, 1

    monkeypatch.setattr(dedupe, "apply_strategy_to_groups", _apply)

    result = dedupe._apply_strategy_from_path(
        source_path,
        {"group": [0]},
        KeeperStrategy.FIRST_OCCURRENCE,
        StrategyParams(),
    )

    assert result == ({"group": 0}, 1)
    assert len(seen) == 1


def test_build_deletes_export_retains_path_metadata_only(tmp_path):
    source_path = tmp_path / "dedupe_buffer.mrc"
    first = _record("one").as_marc()
    second = _record("two").as_marc()
    source_path.write_bytes(first + second)

    export = dedupe._build_deletes_export(
        source_path,
        [("loaded", len(first))],
    )

    assert set(export) == {"path", "file_bytes"}
    assert export["file_bytes"] == len(second)
    with open(export["path"], "rb") as output_fh:
        records = list(
            pymarc.MARCReader(output_fh, to_unicode=True, permissive=True)
        )
    assert [record.get("001").data for record in records] == ["two"]
