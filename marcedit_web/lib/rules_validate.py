"""Rule-driven MARC record validation.

Walks every record and emits an :class:`Issue` for each violation of the
:class:`RuleSet` parsed from ``marc-rules.txt``. The Validate page renders
these alongside the structural issues from ``preflight.run_preflight``.

Issue codes emitted:

* ``rule-unknown-tag``           — field with a tag that has no rule entry
* ``rule-tag-nonrepeatable``     — non-repeatable tag appears 2+ times
* ``rule-bad-indicator``         — indicator char not in the rule's allowed set
* ``rule-bad-subfield``          — subfield code not in ``valid_subfield_codes``
* ``rule-subfield-nonrepeatable``— non-repeatable subfield appears 2+ times
* ``rule-length-mismatch``       — control field has wrong byte length
* ``rule-only-one-1xx``          — record has more than one 1XX field
* ``rule-missing-245``           — record lacks 245

Cross-record dedup checks (``rule-cross-dedup``) are deliberately deferred
to a later stage so they don't double-report ``preflight``'s duplicate-001
check. The ``dedup_keys`` are still parsed and exposed on the RuleSet for
future use.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Iterable

from pymarc import Record

from .errors import Issue
from .rules import FieldRule, RuleSet

logger = logging.getLogger("marcedit_web.rules_validate")


def validate_records(
    records: Iterable[Record], rules: RuleSet
) -> list[Issue]:
    """Apply ``rules`` to ``records`` and return all violations.

    Order: per-record issues in input order, grouped by record_index; no
    file-scope rule issues are emitted yet (the cross-record dedup check
    is deferred — see module docstring).

    Stage 16: ``records`` is any iterable, not just a list, so callers
    can stream over ``store.iter_records()`` without materializing.
    """
    issues: list[Issue] = []
    for i, record in enumerate(records, start=1):
        identifier = _identifier(record)
        issues.extend(_validate_one(record, rules, i, identifier))
    return issues


# ---------------------------------------------------------------------------
# Per-record checks
# ---------------------------------------------------------------------------


def _validate_one(
    record: Record,
    rules: RuleSet,
    record_index: int,
    identifier: str | None,
) -> list[Issue]:
    out: list[Issue] = []

    # Tag-repeatability + unknown-tag pass.
    tags_present: Counter = Counter(f.tag for f in record.fields)
    for tag, count in tags_present.items():
        rule = rules.fields.get(tag)
        if rule is None:
            out.append(_record_issue(
                "info",
                "rule-unknown-tag",
                f"tag {tag!r} has no entry in marc-rules.txt",
                "if this tag is institution-specific, add it to data/marc-rules.txt",
                record_index, identifier,
            ))
            continue
        if rule.repeatability == "NR" and count > 1:
            out.append(_record_issue(
                "warning",
                "rule-tag-nonrepeatable",
                f"tag {tag!r} is non-repeatable but appears {count}× in this record",
                "delete the duplicates or merge them into a single field",
                record_index, identifier,
            ))

    # Cross-record-style rules expressed per-record.
    if rules.cross_record.must_have_245 and record.get("245") is None:
        out.append(_record_issue(
            "warning",
            "rule-missing-245",
            "marc-rules.txt declares 245 must be present; record has no 245",
            "add a 245 title field before loading",
            record_index, identifier,
        ))

    if rules.cross_record.only_one_1xx:
        ones = sum(c for tag, c in tags_present.items() if tag.startswith("1"))
        if ones > 1:
            out.append(_record_issue(
                "warning",
                "rule-only-one-1xx",
                f"marc-rules.txt declares only one 1XX is allowed; record has {ones}",
                "drop the extra main-entry field(s)",
                record_index, identifier,
            ))

    # Per-field detail checks (indicator/subfield/length).
    for f in record.fields:
        rule = rules.fields.get(f.tag)
        if rule is None:
            continue
        out.extend(_check_field_against_rule(f, rule, record_index, identifier))

    return out


def _check_field_against_rule(
    f,
    rule: FieldRule,
    record_index: int,
    identifier: str | None,
) -> list[Issue]:
    out: list[Issue] = []

    # Control fields: only length checks apply (no indicators, no subfields).
    if _is_control_tag(f.tag):
        if rule.length is not None and rule.length.exact is not None:
            data = getattr(f, "data", "") or ""
            if len(data) != rule.length.exact:
                out.append(_record_issue(
                    "warning",
                    "rule-length-mismatch",
                    (
                        f"{f.tag} is {len(data)} bytes; rules say it should be "
                        f"exactly {rule.length.exact}"
                    ),
                    "check the source file for truncation or a wrong dialect",
                    record_index, identifier,
                ))
        return out

    # Indicator validity.
    if rule.ind1 is not None:
        allowed = rule.ind1.allowed_chars()
        actual = (list(f.indicators)[0] if f.indicators else " ")
        if actual not in allowed:
            out.append(_record_issue(
                "warning",
                "rule-bad-indicator",
                (
                    f"{f.tag} ind1 = {actual!r}; allowed: "
                    + _format_allowed(allowed)
                ),
                "see the rule entry for this tag for the valid indicator codes",
                record_index, identifier,
            ))
    if rule.ind2 is not None:
        allowed = rule.ind2.allowed_chars()
        actual = (list(f.indicators)[1] if len(list(f.indicators)) > 1 else " ")
        if actual not in allowed:
            out.append(_record_issue(
                "warning",
                "rule-bad-indicator",
                (
                    f"{f.tag} ind2 = {actual!r}; allowed: "
                    + _format_allowed(allowed)
                ),
                "see the rule entry for this tag for the valid indicator codes",
                record_index, identifier,
            ))

    # Subfield validity + repeatability.
    valid = set(rule.valid_subfield_codes) if rule.valid_subfield_codes else None
    sub_counts: Counter = Counter()
    for sf in f.subfields:
        sub_counts[sf.code] += 1
        if valid is not None and sf.code not in valid:
            out.append(_record_issue(
                "warning",
                "rule-bad-subfield",
                f"{f.tag} ${sf.code} is not in the valid subfield list {rule.valid_subfield_codes!r}",
                "drop the subfield or fix the rule entry if it's missing",
                record_index, identifier,
            ))
    for code, count in sub_counts.items():
        sf_rule = rule.subfields.get(code)
        if sf_rule is None:
            continue
        if sf_rule.repeatability == "NR" and count > 1:
            out.append(_record_issue(
                "warning",
                "rule-subfield-nonrepeatable",
                f"{f.tag} ${code} is non-repeatable but appears {count}× in this field",
                "merge or drop the duplicate subfields",
                record_index, identifier,
            ))

    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_control_tag(tag: str) -> bool:
    """Control-field tags are 001-009 (no indicators, no subfields)."""
    return (
        len(tag) == 3
        and tag.startswith("00")
        and tag[2].isdigit()
        and tag != "000"
    )


def _format_allowed(allowed: set[str]) -> str:
    """Pretty-print an allowed indicator-char set: space → 'blank'."""
    items = sorted(allowed, key=lambda c: (c != " ", c))
    return ", ".join("blank" if c == " " else repr(c) for c in items)


def _identifier(record: Record) -> str | None:
    f001 = record.get("001")
    if f001 is not None and getattr(f001, "data", None):
        return f001.data
    for f in record.get_fields("035"):
        a = f.get_subfields("a")
        if a:
            return a[0]
    return None


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
