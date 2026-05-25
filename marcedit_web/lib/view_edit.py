"""Single-record `.mrk` parse + validation helper for the View page.

The View page's inline-edit flow lets a cataloger mutate one record at
a time inside the existing record-navigation surface. The same parse +
validate plumbing that MarcEditor uses is overkill at the API layer
when there's exactly one record on the wire — this module wraps it
into a single function that:

* re-parses the supplied ``.mrk`` text;
* verifies exactly one record came out;
* runs preflight (single-record subset) + rule validation against
  the loaded rule set;
* returns ``(record, fatal_errors)`` where ``fatal_errors`` is a list
  of cataloger-readable strings the UI can display verbatim.

100K-safe by construction — it operates on exactly one record's
worth of bytes, no matter the batch size.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pymarc

from . import mrk_parser, preflight, rules_validate
from .errors import Issue
from .rules import RuleSet


@dataclass
class SingleRecordParseResult:
    """Outcome of :func:`parse_and_validate_single_record`.

    ``record`` is the parsed ``pymarc.Record`` when validation passed
    cleanly, else ``None``. ``fatal_errors`` are blocking issues
    (malformed ``.mrk`` lines, missing required fields, etc.) that
    prevent commit. ``warnings`` and ``info`` are surfaced for the
    cataloger to read but don't block save. ``line_errors`` carries
    the raw line/column for editor highlighting.
    """

    record: Optional[pymarc.Record] = None
    fatal_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    line_errors: list[mrk_parser.LineError] = field(default_factory=list)
    rule_issues: list[Issue] = field(default_factory=list)

    @property
    def can_save(self) -> bool:
        return self.record is not None and not self.fatal_errors


# LineError codes that block save. Single-record edit is stricter than
# MarcEditor's batch save: codes where the parser couldn't fully parse
# the line (and would silently drop a field on the floor) are fatal so
# the cataloger sees the problem before committing. Recoverable codes
# the parser repairs in place — ``bad-indicator``,
# ``missing-leading-delimiter``, ``trailing-delimiter``,
# ``bad-subfield-code`` — surface as warnings/info from rule validation
# but don't block save.
_FATAL_LINE_CODES = frozenset({
    "missing-leader",
    "ldr-length",
    "bad-line",
    "encoding",
    "no-tag-prefix",
    "leader-invalid",
    "control-field-rejected",
    "variable-field-rejected",
    "missing-indicators",
})


def parse_and_validate_single_record(
    text: str, rule_set: Optional[RuleSet] = None
) -> SingleRecordParseResult:
    """Parse one record's ``.mrk`` text and validate it.

    The cataloger edits exactly one record at a time in the View
    inline editor. A successful parse that returns 0 or 2+ records
    is a fatal error: the cataloger deleted the leader line, or
    pasted in a second record's worth of text by accident.
    """
    result = SingleRecordParseResult()
    parsed, file_errors = mrk_parser.parse_mrk(text or "")
    result.line_errors.extend(file_errors)

    if not parsed:
        result.fatal_errors.append(
            "No record found in the editor — expected one record starting "
            "with a `=LDR` line."
        )
        return result

    if len(parsed) > 1:
        result.fatal_errors.append(
            f"Editor contained {len(parsed)} records — expected exactly one. "
            "Remove the extra `=LDR` block(s)."
        )
        return result

    only = parsed[0]
    result.line_errors.extend(only.errors)

    for err in result.line_errors:
        if err.code in _FATAL_LINE_CODES:
            result.fatal_errors.append(
                f"line {err.line_no}: {err.code} — {err.message}"
            )

    if only.record is None:
        if not result.fatal_errors:
            result.fatal_errors.append(
                "Record could not be assembled from the edited text."
            )
        return result

    # Per-record preflight (no file-scope checks; we're editing one record
    # inside a larger batch, so file-scope issues like duplicate-001 aren't
    # ours to flag here).
    issues = preflight.run_preflight(records=[only.record], malformed=0)
    if rule_set is not None:
        issues = issues + rules_validate.validate_records([only.record], rule_set)
    result.rule_issues = issues

    for iss in issues:
        msg = f"{iss.code}: {iss.message}"
        if iss.severity == "error":
            result.fatal_errors.append(msg)
        elif iss.severity == "warning":
            result.warnings.append(msg)
        else:
            result.info.append(msg)

    if not result.fatal_errors:
        result.record = only.record

    return result
