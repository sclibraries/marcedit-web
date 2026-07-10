"""Configurable FOLIO profile rules and safe fixes (TASK-148)."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import json
from typing import Any, Iterable

import pymarc
from pymarc import Field, Subfield

from . import db
from . import mrk_writer
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
    collection_name: str = ""
    score_loading: bool = False
    use_949: bool = False
    multi_institution: bool = False


@dataclass(frozen=True)
class FolioIssue:
    issue: Issue
    rule_key: str
    fix_available: bool


@dataclass(frozen=True)
class FolioFixPlan:
    rule_key: str
    record_index: int
    label: str
    before: str
    after: str
    operation: str


@dataclass(frozen=True)
class FolioBatchPreview:
    total_fixes: int
    affected_records: int
    by_rule: dict[str, int]
    samples: list[FolioFixPlan]


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
    FolioRule(
        key="folio-required-035-container",
        profile_key="folio-new-instance",
        label="035 9\\ container code should be present",
        severity="warning",
        target={
            "kind": "field",
            "tag": "035",
            "indicators": ["9", "\\"],
            "subfields": {"a": "{container_code}"},
        },
        requirement={
            "kind": "field_with_context_subfields",
            "context_key": "container_code",
        },
        fix={
            "operation": "add_context_field",
            "tag": "035",
            "indicators": ["9", "\\"],
            "subfields": [["a", "{container_code}"]],
        },
        enabled=True,
    ),
    FolioRule(
        key="folio-multi-institution-506",
        profile_key="folio-new-instance",
        label="506 1\\ should be present for multi-institution loads",
        severity="warning",
        target={"kind": "field", "tag": "506", "indicators": ["1", "\\"]},
        requirement={
            "kind": "required_when_context_true",
            "context_key": "multi_institution",
        },
        fix={"operation": "none"},
        enabled=True,
    ),
    FolioRule(
        key="folio-recommended-710-local",
        profile_key="folio-new-instance",
        label="710 2\\ local collection access point is recommended",
        severity="info",
        target={
            "kind": "field",
            "tag": "710",
            "indicators": ["2", "\\"],
            "subfields": {"a": "{collection_name}", "2": "local"},
        },
        requirement={
            "kind": "field_with_context_subfields",
            "context_key": "collection_name",
        },
        fix={
            "operation": "add_context_field",
            "tag": "710",
            "indicators": ["2", "\\"],
            "subfields": [["a", "{collection_name}"], ["2", "local"]],
        },
        enabled=True,
    ),
    FolioRule(
        key="folio-recommended-830-local",
        profile_key="folio-new-instance",
        label="830 \\0 local series access point is recommended",
        severity="info",
        target={
            "kind": "field",
            "tag": "830",
            "indicators": ["\\", "0"],
            "subfields": {"a": "{collection_name}", "2": "local"},
        },
        requirement={
            "kind": "field_with_context_subfields",
            "context_key": "collection_name",
        },
        fix={
            "operation": "add_context_field",
            "tag": "830",
            "indicators": ["\\", "0"],
            "subfields": [["a", "{collection_name}"], ["2", "local"]],
        },
        enabled=True,
    ),
    FolioRule(
        key="folio-949-required-subfields",
        profile_key="folio-new-instance",
        label="949 field is missing required FOLIO load subfields",
        severity="warning",
        target={
            "kind": "949_required_subfields",
            "required": ["u", "y", "t", "p", "l", "b", "m"],
        },
        requirement={"kind": "949_required_subfields"},
        fix={"operation": "none"},
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
        if not rule.enabled or not _rule_applies_to_context(rule, context):
            continue
        if _rule_is_violated(record, rule, context):
            fix_available = _fix_available(record, rule, context)
            out.append(
                FolioIssue(
                    issue=make_record_issue(
                        rule.severity,
                        rule.key,
                        _message_for(record, rule),
                        _suggestion_for(rule, fix_available),
                        record_index,
                        identifier,
                    ),
                    rule_key=rule.key,
                    fix_available=fix_available,
                )
            )
    return out


def plan_record_fixes(
    record: pymarc.Record,
    rules: list[FolioRule],
    context: FolioContext,
    *,
    record_index: int = 1,
) -> list[FolioFixPlan]:
    plans: list[FolioFixPlan] = []
    for item in evaluate_record(record, rules, context, record_index=record_index):
        if not item.fix_available:
            continue
        rule = next(rule for rule in rules if rule.key == item.rule_key)
        before = mrk_writer.render_records_mrk([record])
        updated = apply_record_fix(record, rule, context)
        after = mrk_writer.render_records_mrk([updated])
        if before != after:
            plans.append(
                FolioFixPlan(
                    rule_key=rule.key,
                    record_index=record_index,
                    label=rule.label,
                    before=before,
                    after=after,
                    operation=str(rule.fix.get("operation", "none")),
                )
            )
    return plans


def preview_batch_fixes(
    records: Iterable[pymarc.Record],
    rules: list[FolioRule],
    context: FolioContext,
    *,
    sample_limit: int = 10,
) -> FolioBatchPreview:
    by_rule: dict[str, int] = {}
    samples: list[FolioFixPlan] = []
    affected = 0
    total = 0
    for idx, record in enumerate(records, start=1):
        plans = plan_record_fixes(record, rules, context, record_index=idx)
        if not plans:
            continue
        affected += 1
        total += len(plans)
        for plan in plans:
            by_rule[plan.rule_key] = by_rule.get(plan.rule_key, 0) + 1
            if len(samples) < sample_limit:
                samples.append(plan)
    return FolioBatchPreview(
        total_fixes=total,
        affected_records=affected,
        by_rule=by_rule,
        samples=samples,
    )


def apply_batch_fixes_to_store(
    store,
    rules: list[FolioRule],
    context: FolioContext,
) -> FolioBatchPreview:
    by_rule: dict[str, int] = {}
    samples: list[FolioFixPlan] = []
    affected = 0
    total = 0
    for idx, record in enumerate(store.iter_records(), start=1):
        plans = plan_record_fixes(record, rules, context, record_index=idx)
        if not plans:
            continue
        updated = record
        for plan in plans:
            rule = next(rule for rule in rules if rule.key == plan.rule_key)
            updated = apply_record_fix(updated, rule, context)
            by_rule[plan.rule_key] = by_rule.get(plan.rule_key, 0) + 1
            total += 1
            if len(samples) < 10:
                samples.append(plan)
        affected += 1
        store.replace(idx - 1, updated)
    return FolioBatchPreview(
        total_fixes=total,
        affected_records=affected,
        by_rule=by_rule,
        samples=samples,
    )


def apply_record_fix(
    record: pymarc.Record,
    rule: FolioRule,
    context: FolioContext,
) -> pymarc.Record:
    updated = copy.deepcopy(record)
    operation = rule.fix.get("operation", "none")
    if operation == "remove_field":
        if not _is_safe_remove_field_fix(rule, context):
            return updated
        for field in list(updated.get_fields(str(rule.fix["tag"]))):
            updated.remove_field(field)
        return updated
    if operation == "add_field":
        if not _has_field_with_subfields(updated, rule.target):
            updated.add_field(_field_from_fix(rule.fix))
        return updated
    if operation == "add_context_field":
        target = _resolve_context_tokens(rule.target, context)
        if not _has_field_with_subfields(updated, target):
            updated.add_field(
                _field_from_fix(_resolve_context_tokens(rule.fix, context))
            )
        return updated
    if operation == "normalize_barcode_suffix":
        _normalize_subfield_suffix(
            updated,
            tag=str(rule.fix["tag"]),
            code=str(rule.fix["subfield"]),
            suffix=_normalized_suffix(context.institution_suffix),
        )
        return updated
    return updated


def _rule_applies_to_context(rule: FolioRule, context: FolioContext) -> bool:
    return rule.profile_key == context.profile_key or rule.profile_key in context.addons


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
    if kind == "field_with_context_subfields":
        context_value = _context_value(context, str(requirement["context_key"]))
        if not context_value:
            return False
        return not _has_field_with_subfields(
            record,
            _resolve_context_tokens(target, context),
        )
    if kind == "required_when_context_true":
        if not bool(_context_value(context, str(requirement["context_key"]))):
            return False
        if target.get("kind") == "field":
            return not _has_field_with_subfields(record, target)
        return record.get(tag) is None
    if kind == "not_in":
        value = _fixed_byte(record, tag, int(target["position"]))
        return value in set(requirement.get("values", []))
    if kind == "either_group_present":
        return not (_has_holdings_item_path(record) or _has_valid_949(record))
    if kind == "949_required_subfields":
        return _missing_949_subfields(record) != []
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
        if not _is_safe_remove_field_fix(rule, context):
            return False
        return record.get(str(rule.fix.get("tag", ""))) is not None
    if operation == "add_field":
        return True
    if operation == "add_context_field":
        context_key = str(rule.requirement.get("context_key", ""))
        return bool(_context_value(context, context_key))
    if operation == "normalize_barcode_suffix":
        suffix = _normalized_suffix(context.institution_suffix)
        values = _subfield_values(
            record,
            str(rule.fix.get("tag", "")),
            str(rule.fix.get("subfield", "")),
        )
        return bool(suffix and any(value.strip() for value in values))
    return False


def _is_safe_remove_field_fix(rule: FolioRule, context: FolioContext) -> bool:
    return (
        rule.key == "folio-new-load-forbidden-001"
        and rule.profile_key == "folio-new-instance"
        and context.profile_key == "folio-new-instance"
        and str(rule.fix.get("tag", "")) == "001"
    )


def _context_value(context: FolioContext, key: str) -> object:
    return getattr(context, key, "")


def _resolve_context_tokens(value, context: FolioContext):
    if isinstance(value, dict):
        return {
            key: _resolve_context_tokens(inner, context)
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [_resolve_context_tokens(inner, context) for inner in value]
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        return str(_context_value(context, value[1:-1]))
    return value


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


def _field_from_fix(fix: dict[str, object]) -> Field:
    subfields = [
        Subfield(code=str(code), value=str(value))
        for code, value in fix.get("subfields", [])
    ]
    return Field(
        tag=str(fix["tag"]),
        indicators=[str(value) for value in fix.get("indicators", [" ", " "])],
        subfields=subfields,
    )


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
        if list(field.indicators) != ["\\", "\\"]:
            continue
        codes = {
            subfield.code
            for subfield in field.subfields
            if (subfield.value or "").strip()
        }
        if required.issubset(codes) and ("h" in codes or {"h", "i"}.issubset(codes)):
            return True
    return False


def _missing_949_subfields(record: pymarc.Record) -> list[str]:
    required = ["u", "y", "t", "p", "l", "b", "m"]
    fields = record.get_fields("949")
    if not fields:
        return []
    present = set()
    for field in fields:
        present.update(
            subfield.code
            for subfield in field.subfields
            if (subfield.value or "").strip()
        )
    missing = [f"${code}" for code in required if code not in present]
    if "h" not in present and not {"h", "i"}.issubset(present):
        missing.append("$h or $h+$i")
    return missing


def _subfield_values(record: pymarc.Record, tag: str, code: str) -> list[str]:
    values: list[str] = []
    for field in record.get_fields(tag):
        values.extend(field.get_subfields(code))
    return values


def _normalize_subfield_suffix(
    record: pymarc.Record,
    *,
    tag: str,
    code: str,
    suffix: str,
) -> None:
    if not suffix:
        return
    for field in record.get_fields(tag):
        subfields = []
        for subfield in field.subfields:
            if subfield.code != code:
                subfields.append(subfield)
                continue
            value = (subfield.value or "").strip()
            if not value:
                subfields.append(subfield)
                continue
            stem = value.rsplit("-", 1)[0] if "-" in value else value
            subfields.append(Subfield(code=subfield.code, value=f"{stem}{suffix}"))
        field.subfields = subfields


def _normalized_suffix(raw: str) -> str:
    value = (raw or "").strip().upper()
    if not value:
        return ""
    return value if value.startswith("-") else f"-{value}"


def _message_for(record: pymarc.Record, rule: FolioRule) -> str:
    if rule.key == "folio-949-required-subfields":
        missing = ", ".join(_missing_949_subfields(record))
        if missing:
            return f"{rule.label}: missing {missing}"
    return rule.label


def _suggestion_for(rule: FolioRule, fix_available: bool) -> str:
    if fix_available:
        return "Use the FOLIO safe-fix action to apply the configured correction."
    if rule.key == "folio-roundtrip-required-001":
        return "Restore the FOLIO SRS 001 before loading; the app cannot infer it safely."
    if rule.key == "folio-949-required-subfields":
        return "Complete the 949 load field before loading to FOLIO."
    return "Review this record against the selected FOLIO profile."


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
