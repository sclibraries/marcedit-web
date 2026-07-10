#!/usr/bin/env python3
"""Opt-in synthetic benchmark for TASK-147 large-batch acceptance."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pymarc

from marcedit_web.lib import batch_runtime, quick_batch
from marcedit_web.lib.quick_batch import QuickBatchRequest
from marcedit_web.lib.record_store import RecordStore


def _record(index: int) -> pymarc.Record:
    record = pymarc.Record()
    record.leader = pymarc.Leader("00000nam a2200000 a 4500")
    record.add_field(pymarc.Field(tag="001", data=f"{index:09d}"))
    record.add_field(
        pymarc.Field(
            tag="245",
            indicators=["0", "0"],
            subfields=[
                pymarc.Subfield(code="a", value=f"Synthetic title {index}")
            ],
        )
    )
    return record


def _write_fixture(path: Path, record_count: int) -> int:
    with path.open("wb") as output:
        writer = pymarc.MARCWriter(output)
        for index in range(record_count):
            writer.write(_record(index))
    return path.stat().st_size


def run_benchmark(
    record_count: int,
    *,
    workdir: Path | None = None,
) -> dict[str, int | float | str]:
    """Run one position lookup and one full quick operation."""
    if record_count < 1:
        raise ValueError("record_count must be at least 1")

    owns_workdir = workdir is None
    if workdir is None:
        root = Path(tempfile.mkdtemp(prefix="marcedit-web-benchmark-"))
    else:
        root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    preview = None
    initial_peak = batch_runtime.peak_rss_bytes()
    try:
        input_path = root / "synthetic.mrc"
        input_bytes = _write_fixture(input_path, record_count)
        store = RecordStore.from_path(input_path)

        lookup_started = time.perf_counter()
        last_record = store.get(record_count - 1)
        lookup_ms = (time.perf_counter() - lookup_started) * 1000
        control_number = last_record.get("001") if last_record else None
        if control_number is None:
            raise RuntimeError("last synthetic record could not be read")
        last_record_id = control_number.data

        operation_started = time.perf_counter()
        preview = quick_batch.build_preview(
            store,
            QuickBatchRequest(kind="leader", position="05", value="c"),
        )
        result = quick_batch.apply_preview(store, preview)
        operation_seconds = time.perf_counter() - operation_started
        if result.error:
            raise RuntimeError(result.error)

        final_record = store.get(record_count - 1)
        if final_record is None or str(final_record.leader)[5] != "c":
            raise RuntimeError("quick operation did not update the last record")

        peak_rss = batch_runtime.peak_rss_bytes()
        return {
            "records": record_count,
            "final_records": store.count(),
            "changed_records": result.changed_count,
            "last_record_id": last_record_id,
            "lookup_ms": round(lookup_ms, 3),
            "operation_seconds": round(operation_seconds, 3),
            "input_bytes": input_bytes,
            "peak_rss_bytes": peak_rss,
            "peak_rss_delta_bytes": max(0, peak_rss - initial_peak),
        }
    finally:
        quick_batch.cleanup_preview(preview)
        if owns_workdir:
            shutil.rmtree(root, ignore_errors=True)


def _threshold_failures(
    result: dict[str, int | float | str],
    *,
    max_lookup_ms: float,
    max_operation_seconds: float,
) -> list[str]:
    failures = []
    records = int(result["records"])
    if int(result["final_records"]) != records:
        failures.append("final record count differs from input")
    if int(result["changed_records"]) != records:
        failures.append("quick operation did not change every input record")
    if float(result["lookup_ms"]) > max_lookup_ms:
        failures.append(f"lookup exceeded {max_lookup_ms:g} ms")
    if float(result["operation_seconds"]) > max_operation_seconds:
        failures.append(
            f"quick operation exceeded {max_operation_seconds:g} seconds"
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=100_000)
    parser.add_argument("--max-lookup-ms", type=float, default=250.0)
    parser.add_argument("--max-operation-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    result = run_benchmark(args.records)
    print(json.dumps(result, sort_keys=True))
    failures = _threshold_failures(
        result,
        max_lookup_ms=args.max_lookup_ms,
        max_operation_seconds=args.max_operation_seconds,
    )
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
