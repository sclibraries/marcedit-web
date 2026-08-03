#!/usr/bin/env python3
"""Capture TASK-194 Gate-0 facts without mutating production."""

from __future__ import annotations

import argparse
from pathlib import Path

from marcedit_web.lib.task_194_runtime import capture_lineage, write_lineage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/private/tmp/marcedit-task-194-runtime-lineage.json"),
    )
    args = parser.parse_args()
    write_lineage(args.output, capture_lineage(args.root))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

