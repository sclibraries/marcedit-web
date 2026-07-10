"""Configurable FOLIO profile rules and safe fixes (TASK-148)."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable

import pymarc

from . import db
from .errors import Issue, make_record_issue


@dataclass(frozen=True)
class FolioProfile:
    key: str
    label: str
    description: str
    is_addon: bool
    enabled: bool


@dataclass(frozen=True)
class FolioRule:
    key: str
    profile_key: str
    label: str
    severity: str
    target: dict[str, Any]
    requirement: dict[str, Any]
    fix: dict[str, Any]
    enabled: bool


@dataclass(frozen=True)
class FolioContext:
    profile_key: str
    addons: tuple[str, ...] = ()
    container_code: str = ""
    institution_suffix: str = ""
    score_loading: bool = False
    use_949: bool = False


@dataclass(frozen=True)
class FolioIssue:
    issue: Issue
    rule_key: str
    fix_available: bool


_DEFAULT_RULES: tuple[FolioRule, ...] = (
    FolioRule(
        key="folio-new-load-forbidden-001",
        profile_key="folio-new-instance",
        label="001 must be absent for new FOLIO Instance/SRS loads",
        severity="warning",
        target={"kind": "field", "tag": "001"},
        requirement={"kind": "forbidden"},
        fix={"operation": "remove_field", "tag": "001"},
        enabled=True,
    ),
    FolioRule(
        key="folio-roundtrip-required-001",
        profile_key="folio-round-trip",
        label="001 must be present when round-tripping FOLIO Instance/SRS records",
        severity="error",
        target={"kind": "field", "tag": "001"},
        requirement={"kind": "required"},
        fix={"operation": "none"},
        enabled=True,
    ),
    FolioRule(
        key="folio-ebook-required-655",
        profile_key="folio-ecollection-ebook",
        label="Electronic books genre/form term should be present",
        severity="warning",
        target={
            "kind": "field",
            "tag": "655",
            "indicators": [" ", "7"],
            "subfields": {"a": "Electronic books.", "2": "local"},
        },
        requirement={"kind": "field_with_subfields"},
        fix={
            "operation": "add_field",
            "tag": "655",
            "indicators": [" ", "7"],
            "subfields": [["a", "Electronic books."], ["2", "local"]],
        },
        enabled=True,
    ),
    FolioRule(
        key="folio-008-byte-29-not-govdoc",
        profile_key="folio-new-instance",
        label="008 byte 29 must not mark records as government documents",
        severity="warning",
        target={"kind": "fixed_byte", "tag": "008", "position": 29},
        requirement={"kind": "not_in", "values": ["s", "z", "o"]},
        fix={"operation": "none"},
        enabled=True,
    ),
    FolioRule(
        key="folio-loading-path-required",
        profile_key="folio-new-instance",
        label="FOLIO load path requires either holdings/item fields or 949",
        severity="warning",
        target={"kind": "loading_path"},
        requirement={"kind": "either_group_present"},
        fix={"operation": "none"},
        enabled=True,
    ),
    FolioRule(
        key="folio-949-barcode-suffix",
        profile_key="folio-new-instance",
        label="949 $b barcode should end in configured institution suffix",
        severity="warning",
        target={"kind": "subfield_suffix", "tag": "949", "subfield": "b"},
        requirement={
            "kind": "suffix_from_context",
            "context_key": "institution_suffix",
        },
        fix={"operation": "normalize_barcode_suffix", "tag": "949", "subfield": "b"},
        enabled=True,
    ),
)


def default_rules_for_tests() -> list[FolioRule]:
    return list(_DEFAULT_RULES)


def list_profiles() -> list[FolioProfile]:
    db.init_schema()
    with db.connect() as conn:
        rows = list(
            conn.execute(
                "SELECT * FROM folio_profiles"
                " WHERE enabled = 1 ORDER BY is_addon, label"
            )
        )
    return [_profile_from_row(row) for row in rows]


def get_profile(key: str) -> FolioProfile | None:
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM folio_profiles WHERE key = ? AND enabled = 1",
            (key,),
        ).fetchone()
    return _profile_from_row(row) if row else None


def rules_for_profile(
    profile_key: str,
    *,
    include_addons: tuple[str, ...] = (),
) -> list[FolioRule]:
    db.init_schema()
    keys = (profile_key, *include_addons)
    placeholders = ",".join("?" for _ in keys)
    with db.connect() as conn:
        rows = list(
            conn.execute(
                f"SELECT folio_rules.* FROM folio_rules"
                f" JOIN folio_profiles"
                f" ON folio_profiles.key = folio_rules.profile_key"
                f" WHERE folio_rules.enabled = 1"
                f" AND folio_profiles.enabled = 1"
                f" AND folio_rules.profile_key IN ({placeholders})"
                f" ORDER BY folio_rules.profile_key, folio_rules.key",
                keys,
            )
        )
    return [_rule_from_row(row) for row in rows]


def evaluate_records(
    records: Iterable[pymarc.Record],
    rules: list[FolioRule],
    context: FolioContext,
) -> list[FolioIssue]:
    out: list[FolioIssue] = []
    for idx, record in enumerate(records, start=1):
        out.extend(evaluate_record(record, rules, context, record_index=idx))
    return out


def evaluate_record(
    record: pymarc.Record,
    rules: list[FolioRule],
    context: FolioContext,
    *,
    record_index: int = 1,
) -> list[FolioIssue]:
    identifier = _identifier(record)
    out: list[FolioIssue] = []
    for rule in rules:
        if not rule.enabled:
            continue
        if _rule_is_violated(record, rule, context):
            out.append(
                FolioIssue(
                    issue=make_record_issue(
                        rule.severity,
                        rule.key,
                        rule.label,
                        _suggestion_for(rule, context),
                        record_index,
                        identifier,
                    ),
                    rule_key=rule.key,
                    fix_available=_fix_available(record, rule, context),
                )
            )
    return out


def _rule_is_violated(
    record: pymarc.Record,
    rule: FolioRule,
    context: FolioContext,
) -> bool:
    target = rule.target
    requirement = rule.requirement
    kind = requirement.get("kind")
    tag = str(target.get("tag", ""))

    if kind == "forbidden":
        return record.get(tag) is not None
    if kind == "required":
        return record.get(tag) is None
    if kind == "field_with_subfields":
        return not _has_field_with_subfields(record, target)
    if kind == "not_in":
        value = _fixed_byte(record, tag, int(target["position"]))
        return value in set(requirement.get("values", []))
    if kind == "either_group_present":
        return not (_has_holdings_item_path(record) or _has_valid_949(record))
    if kind == "suffix_from_context":
        suffix = _normalized_suffix(context.institution_suffix)
        if not suffix:
            return False
        return any(
            not value.endswith(suffix)
            for value in _subfield_values(record, tag, str(target["subfield"]))
        )
    return False


def _fix_available(
    record: pymarc.Record,
    rule: FolioRule,
    context: FolioContext,
) -> bool:
    operation = rule.fix.get("operation", "none")
    if operation == "remove_field":
        return record.get(str(rule.fix.get("tag", ""))) is not None
    if operation == "add_field":
        return True
    if operation == "normalize_barcode_suffix":
        suffix = _normalized_suffix(context.institution_suffix)
        values = _subfield_values(
            record,
            str(rule.fix.get("tag", "")),
            str(rule.fix.get("subfield", "")),
        )
        return bool(suffix and any(value.strip() for value in values))
    return False


def _identifier(record: pymarc.Record) -> str | None:
    f001 = record.get("001")
    if f001 is not None and getattr(f001, "data", None):
        return f001.data
    for field in record.get_fields("035"):
        values = field.get_subfields("a")
        if values:
            return values[0]
    return None


def _has_field_with_subfields(
    record: pymarc.Record,
    target: dict[str, object],
) -> bool:
    tag = str(target["tag"])
    expected = dict(target.get("subfields", {}))
    indicators = target.get("indicators")
    for field in record.get_fields(tag):
        if indicators is not None and list(field.indicators) != list(indicators):
            continue
        if all(
            expected_value in field.get_subfields(code)
            for code, expected_value in expected.items()
        ):
            return True
    return False


def _fixed_byte(record: pymarc.Record, tag: str, position: int) -> str | None:
    field = record.get(tag)
    data = getattr(field, "data", "") if field is not None else ""
    if len(data) <= position:
        return None
    return data[position]


def _has_holdings_item_path(record: pymarc.Record) -> bool:
    return all(record.get(tag) is not None for tag in ("852", "856", "876", "877"))


def _has_valid_949(record: pymarc.Record) -> bool:
    required = {"u", "y", "t", "p", "l", "b", "m"}
    for field in record.get_fields("949"):
        codes = {
            subfield.code
            for subfield in field.subfields
            if (subfield.value or "").strip()
        }
        if required.issubset(codes) and ("h" in codes or {"h", "i"}.issubset(codes)):
            return True
    return False


def _subfield_values(record: pymarc.Record, tag: str, code: str) -> list[str]:
    values: list[str] = []
    for field in record.get_fields(tag):
        values.extend(field.get_subfields(code))
    return values


def _normalized_suffix(raw: str) -> str:
    value = (raw or "").strip().upper()
    if not value:
        return ""
    return value if value.startswith("-") else f"-{value}"


def _suggestion_for(rule: FolioRule, context: FolioContext) -> str:
    if _fix_available_empty_context(rule):
        return "Use the FOLIO safe-fix action to apply the configured correction."
    if rule.key == "folio-roundtrip-required-001":
        return "Restore the FOLIO SRS 001 before loading; the app cannot infer it safely."
    return "Review this record against the selected FOLIO profile."


def _fix_available_empty_context(rule: FolioRule) -> bool:
    return rule.fix.get("operation") in {
        "remove_field",
        "add_field",
        "normalize_barcode_suffix",
    }


def _profile_from_row(row) -> FolioProfile:
    return FolioProfile(
        key=row["key"],
        label=row["label"],
        description=row["description"],
        is_addon=bool(row["is_addon"]),
        enabled=bool(row["enabled"]),
    )


def _rule_from_row(row) -> FolioRule:
    return FolioRule(
        key=row["key"],
        profile_key=row["profile_key"],
        label=row["label"],
        severity=row["severity"],
        target=json.loads(row["target_json"]),
        requirement=json.loads(row["requirement_json"]),
        fix=json.loads(row["fix_json"]),
        enabled=bool(row["enabled"]),
    )
