"""Pre-flight validation for marcedit-web.

Pre-flight runs before any write or batch transform. It walks every record
and returns a flat `list[Issue]`. The caller decides what to do with each
issue based on its severity:

* `error`   blocks the run (writers never open)
* `warning` advises but allows the run (strict mode promotes to error)
* `info`    purely informational (record counts, etc.)

What this checks:

* File-scope: existence, readability, non-empty, parseable records,
  malformed-record count, expected-count mismatch (if supplied).
* Per-record: leader length, missing 001/245/856, empty 856 $u.
* Cross-record: duplicate 001, duplicate OCLC 035 $a, duplicate LCCN 010 $a.

Pre-parsed fast path: callers that already hold the parsed records in
memory (the Streamlit pages do, after upload) can pass `records=` and
`malformed=` to skip the file-read.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from pymarc import MARCReader

from .errors import Issue

logger = logging.getLogger("marcedit_web.preflight")


def run_preflight(
    input_path: Path | None = None,
    *,
    records: list | None = None,
    malformed: int = 0,
    expected_count: int | None = None,
) -> list[Issue]:
    """Validate records (or read `input_path` and validate).

    Returns a list of `Issue` objects in deterministic order: file-scope
    first, then record-scope by `record_index`. The list may be empty
    (no problems found).

    Never raises on validation problems — every issue comes back via the
    return value. An unexpected IO failure beyond "file doesn't exist"
    propagates up so callers can decide whether to log+exit or wrap into
    a `PreflightError`.

    Pre-parsed fast path: pass `records=` and `malformed=` to skip the
    file-read and re-parse. When neither `input_path` nor `records` is
    supplied, returns an empty list.
    """
    issues: list[Issue] = []

    pre_parsed = records is not None

    if not pre_parsed and input_path is None:
        return issues

    # --- File-scope checks --------------------------------------------------
    # Skipped when the caller has already parsed: existence, read, and
    # empty-file are guaranteed by the prior successful parse.
    raw_bytes: bytes | None = None
    if not pre_parsed:
        assert input_path is not None  # narrowed above
        if not input_path.exists():
            return [Issue(
                severity="error",
                scope="file",
                code="input-missing",
                message=f"input file does not exist: {input_path}",
                suggestion="check the path or re-upload the file",
                file_path=str(input_path),
            )]
        try:
            raw_bytes = input_path.read_bytes()
        except OSError as exc:
            return [Issue(
                severity="error",
                scope="file",
                code="input-unreadable",
                message=f"could not read {input_path}: {exc}",
                suggestion="check file permissions or whether another process has it open",
                file_path=str(input_path),
            )]
        if not raw_bytes:
            return [Issue(
                severity="error",
                scope="file",
                code="input-empty",
                message=f"input file is empty: {input_path}",
                file_path=str(input_path),
            )]

    # --- Parse records ------------------------------------------------------
    # On the pre-parsed fast path, the caller has already done this work and
    # passed both the records list and the malformed count in.
    if not pre_parsed:
        assert raw_bytes is not None
        records = []
        malformed = 0
        reader = MARCReader(io.BytesIO(raw_bytes), to_unicode=True, permissive=True)
        for record in reader:
            if record is None:
                malformed += 1
                continue
            records.append(record)

    if not records and malformed == 0:
        file_path_str = str(input_path) if input_path is not None else None
        name = input_path.name if input_path is not None else "input"
        issues.append(Issue(
            severity="error",
            scope="file",
            code="no-records",
            message=f"no parseable records in {name}",
            suggestion="confirm the file is a binary .mrc and not a .mrk/.txt export",
            file_path=file_path_str,
        ))
        return issues

    file_path_str = str(input_path) if input_path is not None else None

    if malformed > 0:
        issues.append(Issue(
            severity="warning",
            scope="file",
            code="malformed-records",
            message=(
                f"{malformed} record{'s' if malformed != 1 else ''} could not "
                f"be parsed and will be skipped"
            ),
            suggestion=(
                "if the count is unexpectedly high, the file may be truncated "
                "or use a different MARC dialect"
            ),
            file_path=file_path_str,
        ))

    # Record-count info — useful in the report tab.
    issues.append(Issue(
        severity="info",
        scope="file",
        code="record-count",
        message=f"{len(records)} parseable record{'s' if len(records) != 1 else ''}",
        file_path=file_path_str,
    ))

    if expected_count is not None and len(records) != expected_count:
        issues.append(Issue(
            severity="warning",
            scope="file",
            code="record-count-mismatch",
            message=(
                f"expected {expected_count} record"
                f"{'s' if expected_count != 1 else ''}, "
                f"found {len(records)} parseable"
            ),
            suggestion="confirm the manifest figure; if the input is truncated, re-export",
            file_path=file_path_str,
        ))

    # --- Per-record checks --------------------------------------------------
    seen_001: dict[str, list[int]] = {}
    seen_oclc: dict[str, list[int]] = {}
    seen_lccn: dict[str, list[int]] = {}

    for i, record in enumerate(records, start=1):
        identifier = _identifier(record)

        # Leader length: should always be 24. pymarc enforces this on parse,
        # so a parseable record having the wrong leader length is unusual but
        # worth flagging if it ever happens.
        try:
            leader_str = str(record.leader)
        except Exception:  # noqa: BLE001 - bad leader can't be stringified
            leader_str = ""
        if len(leader_str) != 24:
            issues.append(_record_issue(
                "error", "leader-length-invalid",
                f"leader is {len(leader_str)} bytes (expected 24)",
                "review this record; the leader may be corrupt",
                i, identifier,
            ))

        if record.get("001") is None:
            issues.append(_record_issue(
                "warning", "missing-001",
                "no 001 control field",
                "001 is the system control number; many downstream systems require it",
                i, identifier,
            ))
        if record.get("245") is None:
            issues.append(_record_issue(
                "warning", "missing-245",
                "no 245 title field",
                "discovery match relies on 245; review before upload",
                i, identifier,
            ))

        f856_list = record.get_fields("856")
        if not f856_list:
            issues.append(_record_issue(
                "warning", "missing-856",
                "no 856 access URL field",
                "electronic-resource loads need at least one 856 with a usable $u",
                i, identifier,
            ))
        else:
            for f in f856_list:
                u_values = f.get_subfields("u")
                if any(not (u or "").strip() for u in u_values):
                    issues.append(_record_issue(
                        "warning", "empty-856-u",
                        "856 has an empty $u",
                        "review the access URL before upload",
                        i, identifier,
                    ))
                    break  # one warning per record is enough

        # Track duplicates for the cross-record pass below.
        cn_001 = _control_value(record, "001")
        if cn_001:
            seen_001.setdefault(cn_001, []).append(i)
        for oclc in _oclc_values(record):
            seen_oclc.setdefault(oclc, []).append(i)
        for lccn in _lccn_values(record):
            seen_lccn.setdefault(lccn, []).append(i)

    # --- Cross-record duplicate checks --------------------------------------
    issues.extend(_duplicate_issues(seen_001, "duplicate-001", "001 control field"))
    issues.extend(_duplicate_issues(seen_oclc, "duplicate-oclc-035", "OCLC 035 $a"))
    issues.extend(_duplicate_issues(seen_lccn, "duplicate-lccn-010", "LCCN 010 $a"))

    return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _identifier(record) -> str | None:
    """Best-available identifier for a record (001 → first 035 $a → None)."""
    cn_001 = _control_value(record, "001")
    if cn_001:
        return cn_001
    for f in record.get_fields("035"):
        a = f.get_subfields("a")
        if a:
            return a[0]
    return None


def _control_value(record, tag: str) -> str | None:
    f = record.get(tag)
    if f is None:
        return None
    data = getattr(f, "data", None)
    return data.strip() if data else None


def _oclc_values(record) -> list[str]:
    """Return all 035 $a values that look like OCLC identifiers."""
    out: list[str] = []
    for f in record.get_fields("035"):
        for v in f.get_subfields("a"):
            if v and ("(OCoLC)" in v or v.strip().isdigit()):
                out.append(v.strip())
    return out


def _lccn_values(record) -> list[str]:
    out: list[str] = []
    for f in record.get_fields("010"):
        for v in f.get_subfields("a"):
            if v and v.strip():
                out.append(v.strip())
    return out


def _record_issue(
    severity: str,
    code: str,
    message: str,
    suggestion: str | None,
    record_index: int,
    identifier: str | None,
) -> Issue:
    return Issue(
        severity=severity,  # type: ignore[arg-type]
        scope="record",
        code=code,
        message=message,
        suggestion=suggestion,
        record_index=record_index,
        identifier=identifier,
    )


def _duplicate_issues(
    seen: dict[str, list[int]],
    code: str,
    label: str,
) -> list[Issue]:
    """Convert a {value: [indices]} map into one Issue per duplicated value."""
    issues: list[Issue] = []
    for value, indices in seen.items():
        if len(indices) < 2:
            continue
        first = indices[0]
        rest = indices[1:]
        rest_text = ", ".join(f"#{i}" for i in rest[:5])
        if len(rest) > 5:
            rest_text += f" (+{len(rest) - 5} more)"
        issues.append(Issue(
            severity="warning",
            scope="record",
            code=code,
            message=(
                f"{label} {value!r} appears in {len(indices)} records "
                f"(#{first}, {rest_text})"
            ),
            suggestion=(
                "duplicates can create double match points after stamping; "
                "review the affected records before upload"
            ),
            record_index=first,
            identifier=value,
        ))
    return issues


# ---------------------------------------------------------------------------
# Convenience helpers for callers
# ---------------------------------------------------------------------------


def summarize(issues: list[Issue]) -> dict[str, int]:
    """Count issues by severity. Useful for the Validate and Report pages."""
    out = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        out[issue.severity] = out.get(issue.severity, 0) + 1
    return out


def has_blocking_errors(issues: list[Issue], *, strict: bool = False) -> bool:
    """True if pre-flight should block the run.

    With `strict=True`, warnings also block.
    """
    for issue in issues:
        if issue.severity == "error":
            return True
        if strict and issue.severity == "warning":
            return True
    return False
