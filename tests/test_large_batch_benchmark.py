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
