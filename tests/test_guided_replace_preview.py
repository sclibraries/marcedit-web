import copy
import io
from pathlib import Path

import pymarc
import pytest
from pymarc import Field, Record, Subfield

from marcedit_web.lib import guided_replace_preview, sandbox
from marcedit_web.lib.record_store import RecordStore


def _record_with_035(value):
    record = Record()
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[Subfield(code="a", value=value)],
        )
    )
    return record


def _record_bytes(record):
    stream = io.BytesIO()
    writer = pymarc.MARCWriter(stream)
    writer.write(record)
    return stream.getvalue()


def _store_with_035(tmp_path, value):
    return RecordStore.from_bytes(
        _record_bytes(_record_with_035(value)),
        tmp_dir=tmp_path / "store",
    )


def _guided_operation(**changes):
    params = {
        "target_kind": "subfield",
        "tag": "035",
        "subfield": "a",
        "match_mode": "contains",
        "find": "TFeba",
        "ignore_case": False,
        "replacement_mode": "matched_text",
        "replacement": "(SCTFEBA)",
        "occurrences": "all",
        "condition": "always",
    }
    params.update(changes)
    return {"kind": "guided-find-replace", "params": params}


def _timed_out_result(tmp_path):
    return sandbox.SandboxResult(
        output_path=tmp_path / "timed-out.mrc",
        errors=[],
        returncode=-9,
        timed_out=True,
    )


def test_preview_runs_compiled_operation_in_sandbox_without_mutating_store(
    tmp_path,
):
    store = _store_with_035(tmp_path, "TFeba9780020306634")
    operation = _guided_operation()
    before = store.get(0)["035"]["a"]

    preview = guided_replace_preview.build_preview(store, operation)

    assert preview.error is None
    assert preview.before == "035 $aTFeba9780020306634"
    assert preview.after == "035 $a(SCTFEBA)9780020306634"
    assert preview.result == {
        "matched_values": 1,
        "changed_values": 1,
        "matched_occurrences": 1,
    }
    assert store.get(0)["035"]["a"] == before


def test_preview_serializes_a_copy_of_an_edited_store_record(
    tmp_path, monkeypatch
):
    store = _store_with_035(tmp_path, "TFeba123")
    edited_record = _record_with_035("TFeba456")
    store.replace(0, edited_record)

    def mutating_serializer(record):
        record["035"]["a"] = "mutated"
        raise RuntimeError("stop after mutation check")

    monkeypatch.setattr(
        guided_replace_preview, "_record_bytes", mutating_serializer
    )

    guided_replace_preview.build_preview(store, _guided_operation())

    assert store.get(0)["035"]["a"] == "TFeba456"


def test_preview_currency_requires_same_store_revision_and_request(tmp_path):
    store = _store_with_035(tmp_path, "TFeba123")
    operation = _guided_operation()
    preview = guided_replace_preview.build_preview(store, operation)
    assert guided_replace_preview.is_current(preview, store, operation)

    changed = copy.deepcopy(operation)
    changed["params"]["replacement"] = "(OTHER)"
    assert not guided_replace_preview.is_current(preview, store, changed)

    other_store = _store_with_035(tmp_path / "other", "TFeba123")
    assert not guided_replace_preview.is_current(
        preview, other_store, operation
    )

    store.replace(0, _record_with_035("TFeba456"))
    assert not guided_replace_preview.is_current(preview, store, operation)


def test_preview_cache_key_is_canonical_normalized_request_json():
    explicit = _guided_operation()
    sparse = {
        "kind": "guided-find-replace",
        "params": {
            "tag": "035",
            "subfield": "a",
            "find": "TFeba",
            "replacement": "(SCTFEBA)",
        },
    }

    assert guided_replace_preview.preview_cache_key(sparse) == (
        guided_replace_preview.preview_cache_key(explicit)
    )


def test_raw_preview_cache_key_does_not_launch_syntax_validation(
    monkeypatch,
):
    operation = _guided_operation(
        match_mode="raw_regex",
        find=r"^(TFeba)(\d+)$",
        replacement=r"(SCTFEBA)\2",
    )
    monkeypatch.setattr(
        guided_replace_preview.guided_replace_validation,
        "validate_raw_regex",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("cache currency must not launch the sandbox")
        ),
    )

    assert guided_replace_preview.preview_cache_key(operation)


def test_oversized_request_fails_loud_and_is_never_current(
    tmp_path, monkeypatch
):
    store = _store_with_035(tmp_path, "TFeba123")
    operation = _guided_operation(
        replacement="x" * (sandbox.MAX_ERROR_MESSAGE_BYTES + 1)
    )
    monkeypatch.setattr(
        guided_replace_preview.sandbox,
        "run_tasks_subprocess",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("oversized request must not reach the sandbox")
        ),
    )

    preview = guided_replace_preview.build_preview(store, operation)

    assert "request" in preview.error.lower()
    assert "limit" in preview.error.lower()
    assert preview.request == {}
    assert len(preview.error.encode("utf-8")) <= (
        sandbox.MAX_ERROR_MESSAGE_BYTES
    )
    assert not guided_replace_preview.is_current(preview, store, operation)
    with pytest.raises(ValueError, match="request.*limit"):
        guided_replace_preview.preview_cache_key(operation)


def test_many_large_selected_values_have_bounded_visible_display(tmp_path):
    record = Record()
    original_values = []
    for index in range(4):
        value = "TFeba{0}{1}".format(index, "x" * 4000)
        original_values.append(value)
        record.add_field(
            Field(
                tag="035",
                indicators=[" ", " "],
                subfields=[Subfield(code="a", value=value)],
            )
        )
    store = RecordStore.from_bytes(
        _record_bytes(record),
        tmp_dir=tmp_path / "large-display",
    )

    preview = guided_replace_preview.build_preview(store, _guided_operation())

    assert preview.error is None
    assert preview.result == {
        "matched_values": 4,
        "changed_values": 4,
        "matched_occurrences": 4,
    }
    assert len(preview.before.encode("utf-8")) <= sandbox.MAX_STDERR_BYTES
    assert len(preview.after.encode("utf-8")) <= sandbox.MAX_STDERR_BYTES
    assert "preview truncated" in preview.before
    assert "4 selected values" in preview.before
    assert "preview truncated" in preview.after
    assert [field["a"] for field in store.get(0).get_fields("035")] == (
        original_values
    )


def test_preview_condition_mismatch_returns_zero_counts(tmp_path):
    store = _store_with_035(tmp_path, "TFeba123")

    preview = guided_replace_preview.build_preview(
        store, _guided_operation(condition="serials")
    )

    assert preview.error is None
    assert preview.result == {
        "matched_values": 0,
        "changed_values": 0,
        "matched_occurrences": 0,
    }
    assert preview.before == preview.after


def test_preview_without_records_returns_clear_no_file_error(tmp_path):
    store = RecordStore.from_bytes(b"", tmp_dir=tmp_path / "empty")

    preview = guided_replace_preview.build_preview(
        store, _guided_operation()
    )

    assert "No loaded record" in preview.error
    assert not guided_replace_preview.is_current(
        preview, store, _guided_operation()
    )


def test_raw_regex_timeout_is_an_error_not_a_current_preview(
    tmp_path, monkeypatch
):
    store = _store_with_035(tmp_path, "TFeba123")
    monkeypatch.setattr(
        guided_replace_preview.sandbox,
        "run_tasks_subprocess",
        lambda *args, **kwargs: _timed_out_result(tmp_path),
    )
    preview = guided_replace_preview.build_preview(
        store, _guided_operation(match_mode="raw_regex")
    )
    assert "timed out" in preview.error
    assert not guided_replace_preview.is_current(
        preview, store, _guided_operation(match_mode="raw_regex")
    )


def test_launcher_error_is_bounded_and_not_current(tmp_path, monkeypatch):
    store = _store_with_035(tmp_path, "TFeba123")
    monkeypatch.setattr(
        guided_replace_preview.sandbox,
        "run_tasks_subprocess",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("launcher failed")
        ),
    )

    preview = guided_replace_preview.build_preview(
        store, _guided_operation(match_mode="raw_regex")
    )

    assert "launcher failed" in preview.error
    assert not guided_replace_preview.is_current(
        preview, store, _guided_operation(match_mode="raw_regex")
    )


def test_preview_always_removes_its_temporary_directory(
    tmp_path, monkeypatch
):
    store = _store_with_035(tmp_path, "TFeba123")
    preview_dir = tmp_path / "preview"

    def make_preview_dir(**_kwargs):
        preview_dir.mkdir()
        return str(preview_dir)

    monkeypatch.setattr(
        guided_replace_preview.tempfile,
        "mkdtemp",
        make_preview_dir,
    )
    monkeypatch.setattr(
        guided_replace_preview.sandbox,
        "run_tasks_subprocess",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("launcher failed")
        ),
    )

    guided_replace_preview.build_preview(store, _guided_operation())

    assert not Path(preview_dir).exists()
