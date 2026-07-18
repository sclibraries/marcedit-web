"""Contract tests for the opt-in synthetic large-batch benchmark."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _benchmark_module():
    path = Path("scripts/benchmark-large-batch.py")
    spec = importlib.util.spec_from_file_location(
        "benchmark_large_batch", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_benchmark_reports_lookup_operation_counts_time_and_rss(tmp_path):
    benchmark = _benchmark_module()

    result = benchmark.run_benchmark(25, workdir=tmp_path / "benchmark")

    assert result["records"] == 25
    assert result["final_records"] == 25
    assert result["changed_records"] == 25
    assert result["last_record_id"] == "000000024"
    assert result["lookup_ms"] >= 0
    assert result["operation_seconds"] >= 0
    assert result["input_bytes"] > 0
    assert result["peak_rss_bytes"] > 0
    assert result["peak_rss_delta_bytes"] >= 0


def test_benchmark_cli_fails_when_threshold_is_exceeded(
    monkeypatch, capsys
):
    benchmark = _benchmark_module()
    monkeypatch.setattr(
        benchmark,
        "run_benchmark",
        lambda records: {
            "records": records,
            "final_records": records,
            "changed_records": records,
            "last_record_id": f"{records - 1:09d}",
            "lookup_ms": 251.0,
            "operation_seconds": 31.0,
            "input_bytes": 1,
            "peak_rss_bytes": 1,
            "peak_rss_delta_bytes": 0,
        },
    )

    exit_code = benchmark.main(["--records", "10"])

    assert exit_code == 1
    assert "lookup exceeded 250 ms" in capsys.readouterr().err


def test_queued_benchmark_reports_durable_chunked_result(tmp_path):
    benchmark = _benchmark_module()

    result = benchmark.run_queued_benchmark(
        12,
        chunk_records=5,
        workdir=tmp_path / "queued-benchmark",
        # Three deliberate 0.75-second chunk delays make the total run exceed
        # the two-second per-chunk limit without leaving a load-sensitive
        # sub-second margin for sandbox startup and MARC I/O in any one chunk.
        per_chunk_limit_seconds=2.0,
        chunk_delay_seconds=0.75,
    )

    assert result["state"] == "completed"
    assert result["operation_id"] > 0
    assert result["attempts"] == 1
    assert result["records"] == 12
    assert result["processed_records"] == 12
    assert result["output_records"] == 12
    assert result["result_records"] == 12
    assert result["error_count"] == 0
    assert result["result_artifacts"] == 1
    assert result["completed_chunks"] == 3
    assert result["elapsed_seconds"] > result["per_chunk_limit_seconds"]
    assert result["peak_rss_bytes"] > 0


def test_benchmark_cli_routes_queued_mode(monkeypatch, capsys):
    benchmark = _benchmark_module()
    monkeypatch.setattr(
        benchmark,
        "run_queued_benchmark",
        lambda records, *, chunk_records: {
            "state": "completed",
            "operation_id": 7,
            "attempts": 1,
            "records": records,
            "processed_records": records,
            "output_records": records,
            "result_records": records,
            "error_count": 0,
            "result_artifacts": 1,
            "completed_chunks": 2,
            "elapsed_seconds": 1.1,
            "per_chunk_limit_seconds": 1.0,
            "peak_rss_bytes": 1,
            "peak_rss_delta_bytes": 0,
        },
    )

    exit_code = benchmark.main(
        ["--queued", "--records", "10", "--chunk-records", "5"]
    )

    assert exit_code == 0
    assert '"operation_id": 7' in capsys.readouterr().out
