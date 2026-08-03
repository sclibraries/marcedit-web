from pathlib import Path
import subprocess

import pytest
from marcedit_web.lib import (
    external_task_migration,
    guided_replace_validation,
    sandbox,
    task_authoring,
)


def _result(tmp_path, *, errors=None, **changes):
    values = {
        "output_path": tmp_path / "output.mrc",
        "errors": list(errors or []),
        "error_count": len(errors or []),
        "returncode": 0,
    }
    values.update(changes)
    return sandbox.SandboxResult(**values)


def _operation_params(**changes):
    params = {
        "target_kind": "subfield",
        "tag": "035",
        "subfield": "a",
        "match_mode": "raw_regex",
        "find": r"^(TFeba)(\d+)$",
        "ignore_case": False,
        "replacement_mode": "matched_text",
        "replacement": r"(SCTFEBA)\2",
        "occurrences": "all",
        "condition": "always",
    }
    params.update(changes)
    return params


@pytest.mark.parametrize(
    "line",
    [
        "SUBFIELD_EDIT\t856\tu\tOld\tNew\t0|0",
        "SUBFIELD_EDIT\t856\tu\t^b\thttps://proxy/\t0|0",
        "SUBFIELD_EDIT\t050\tb\t^e\teb\t0|0",
        "SUBFIELD_EDIT\t856\ty\t\tLink to resource\t101|0",
        "SUBFIELD_REMOVE\t035\tz\t(OCoLC)\t107|0",
    ],
)
def test_automatic_subfield_adapter_outputs_are_valid_authoring_operations(line):
    item = external_task_migration.adapt_instruction(line)

    assert item.status == "converted"
    assert all(
        task_authoring.validate_operation(operation) == ()
        for operation in item.operations
    )


def test_oversized_request_is_rejected_before_raw_validator(monkeypatch):
    called = []
    monkeypatch.setattr(
        guided_replace_validation.sandbox,
        "run_tasks_subprocess",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )

    errors = guided_replace_validation.validate_raw_regex(
        find="TFeba",
        replacement="x" * 3000,
        ignore_case=False,
    )

    assert len(errors) == 1
    error = errors[0]
    assert "request" in error.lower()
    assert "limit" in error.lower()
    assert len(error.encode("utf-8")) <= sandbox.MAX_ERROR_MESSAGE_BYTES
    assert called == []


def test_invalid_capture_reference_is_rejected_in_sandbox():
    errors = guided_replace_validation.validate_raw_regex(
        find=r"(TFeba)",
        replacement=r"\2",
        ignore_case=False,
    )

    assert len(errors) == 1
    assert "invalid group reference" in errors[0]


def test_deeply_nested_pattern_returns_bounded_error_without_crashing():
    errors = guided_replace_validation.validate_raw_regex(
        find="(" * 500,
        replacement="x",
        ignore_case=False,
    )

    assert len(errors) == 1
    assert "RecursionError" in errors[0]
    assert len(errors[0].encode("utf-8")) <= (
        sandbox.MAX_ERROR_MESSAGE_BYTES
    )


def test_timeout_is_fail_closed_and_temporary_directory_is_removed(
    tmp_path, monkeypatch
):
    validation_dir = tmp_path / "validation"

    def make_validation_dir(**_kwargs):
        validation_dir.mkdir()
        return str(validation_dir)

    monkeypatch.setattr(
        guided_replace_validation.tempfile,
        "mkdtemp",
        make_validation_dir,
    )
    monkeypatch.setattr(
        guided_replace_validation.sandbox,
        "run_tasks_subprocess",
        lambda *_args, **_kwargs: _result(
            tmp_path,
            timed_out=True,
            returncode=-9,
        ),
    )

    errors = guided_replace_validation.validate_raw_regex(
        find="TFeba",
        replacement="replacement",
        ignore_case=False,
    )

    assert errors == (
        "Regular expression validation timed out in the sandbox.",
    )
    assert not Path(validation_dir).exists()


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("launcher failed"),
        subprocess.SubprocessError("preexec failed"),
    ],
)
def test_launcher_failure_is_bounded_and_cleans_temporary_directory(
    tmp_path, monkeypatch, failure
):
    validation_dir = tmp_path / "validation"

    def make_validation_dir(**_kwargs):
        validation_dir.mkdir()
        return str(validation_dir)

    monkeypatch.setattr(
        guided_replace_validation.tempfile,
        "mkdtemp",
        make_validation_dir,
    )
    monkeypatch.setattr(
        guided_replace_validation.sandbox,
        "run_tasks_subprocess",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            failure
        ),
    )

    errors = guided_replace_validation.validate_raw_regex(
        find="TFeba",
        replacement="replacement",
        ignore_case=False,
    )

    assert str(failure) in errors[0]
    assert len(errors[0].encode("utf-8")) <= (
        sandbox.MAX_ERROR_MESSAGE_BYTES
    )
    assert not Path(validation_dir).exists()


def test_child_diagnostics_and_nonzero_exit_are_bounded(
    tmp_path, monkeypatch
):
    results = iter([
        _result(
            tmp_path,
            errors=[{
                "message": "MemoryError: " + "x" * 10000,
            }],
        ),
        _result(
            tmp_path,
            returncode=9,
            stderr="child failed",
        ),
    ])
    monkeypatch.setattr(
        guided_replace_validation.sandbox,
        "run_tasks_subprocess",
        lambda *_args, **_kwargs: next(results),
    )

    memory_error = guided_replace_validation.validate_raw_regex(
        find="TFeba",
        replacement="replacement",
        ignore_case=False,
    )
    nonzero_error = guided_replace_validation.validate_raw_regex(
        find="TFeba",
        replacement="replacement",
        ignore_case=False,
    )

    assert "MemoryError" in memory_error[0]
    assert len(memory_error[0].encode("utf-8")) <= (
        sandbox.MAX_ERROR_MESSAGE_BYTES
    )
    assert "code 9" in nonzero_error[0]
