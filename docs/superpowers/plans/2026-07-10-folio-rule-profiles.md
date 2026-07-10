# FOLIO Rule Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build configurable FOLIO validation profiles with safe assisted fixes for both batch preview/application and per-record issue repair.

**Architecture:** Add a constrained structured rule engine in `marcedit_web/lib/folio_profiles.py`, backed by SQLite-seeded profile/rule definitions. Validate calls the FOLIO evaluator after the existing preflight/rules/load-readiness pipeline, then delegates deterministic record changes to pure planning/apply helpers that operate on `pymarc.Record` objects and the existing disk-backed `RecordStore`.

**Tech Stack:** Python 3, Streamlit, SQLite via `marcedit_web.lib.db`, pymarc, pytest.

## Global Constraints

- Ticket: `.tickets/TASK-148-folio-rule-profiles.md`.
- Design spec: `docs/superpowers/specs/2026-07-10-folio-rule-profiles-design.md`.
- Use TDD: write each test first and verify the red failure before production code.
- Keep FOLIO rules structured data; do not execute arbitrary Python for rules or fixes.
- Do not add direct FOLIO API integration.
- Do not silently apply FOLIO fixes during export.
- Keep validation and preview streaming over `store.iter_records()` where a full batch is involved.
- Do not store full record lists in Streamlit session state.
- Preserve existing `Issue` dataclass usage and use stable `folio-` issue codes.
- Touch only the files named in each task.

---

## File Structure

- Create `marcedit_web/lib/folio_profiles.py`: dataclasses, seeded profile/rule definitions, rule loading, evaluation, safe-fix planning, and record-level fix application.
- Modify `marcedit_web/lib/db.py`: add schema version 11, tables `folio_profiles` and `folio_rules`, and idempotent seed migration.
- Modify `marcedit_web/render/validate.py`: render FOLIO controls, include FOLIO issues, show fix availability, and wire per-record/batch fix actions.
- Modify `marcedit_web/render/_record_modal.py`: optionally render a supplied safe-fix button callback in the existing record modal.
- Modify `marcedit_web/lib/view_edit.py`: remove direct hard-coded `load_readiness` dependence only after Validate owns FOLIO profile checks; otherwise leave it unchanged in this plan.
- Create tests:
  - `tests/test_folio_profile_db.py`
  - `tests/test_folio_profiles.py`
  - `tests/test_folio_profile_fixes.py`
  - `tests/test_validate_folio_profiles.py`

---

### Task 1: SQLite Storage and Seeded Profile Loading

**Files:**
- Modify: `marcedit_web/lib/db.py`
- Create: `marcedit_web/lib/folio_profiles.py`
- Test: `tests/test_folio_profile_db.py`

**Interfaces:**
- Produces: `folio_profiles.list_profiles() -> list[FolioProfile]`
- Produces: `folio_profiles.get_profile(key: str) -> FolioProfile | None`
- Produces: `folio_profiles.rules_for_profile(profile_key: str, *, include_addons: tuple[str, ...] = ()) -> list[FolioRule]`
- Produces dataclasses:
  - `FolioProfile(key: str, label: str, description: str, is_addon: bool, enabled: bool)`
  - `FolioRule(key: str, profile_key: str, label: str, severity: str, target: dict[str, object], requirement: dict[str, object], fix: dict[str, object], enabled: bool)`

- [ ] **Step 1: Write failing storage tests**

Add `tests/test_folio_profile_db.py`:

```python
from __future__ import annotations

from marcedit_web.lib import db, folio_profiles


def test_folio_seed_migration_creates_default_profiles_and_rules(tmp_path, monkeypatch):
    """Default FOLIO standards are available after schema initialization."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "folio.db"))
    db.reset_for_tests()
    db.init_schema()

    profiles = {profile.key: profile for profile in folio_profiles.list_profiles()}

    assert set(profiles) >= {
        "folio-new-instance",
        "folio-round-trip",
        "folio-ecollection-ebook",
    }
    assert profiles["folio-ecollection-ebook"].is_addon is True

    new_rules = {rule.key: rule for rule in folio_profiles.rules_for_profile("folio-new-instance")}
    assert "folio-new-load-forbidden-001" in new_rules
    assert new_rules["folio-new-load-forbidden-001"].fix["operation"] == "remove_field"


def test_folio_seed_migration_is_idempotent(tmp_path, monkeypatch):
    """Seeding twice must not duplicate local FOLIO profiles or rules."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "folio.db"))
    db.reset_for_tests()
    db.init_schema()
    db.reset_for_tests()
    db.init_schema()

    profiles = [profile.key for profile in folio_profiles.list_profiles()]
    rules = [rule.key for rule in folio_profiles.rules_for_profile("folio-new-instance")]

    assert profiles.count("folio-new-instance") == 1
    assert rules.count("folio-new-load-forbidden-001") == 1


def test_rules_for_profile_can_include_addon_rules(tmp_path, monkeypatch):
    """The ebook add-on layers onto a primary workflow profile."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "folio.db"))
    db.reset_for_tests()
    db.init_schema()

    rules = folio_profiles.rules_for_profile(
        "folio-new-instance",
        include_addons=("folio-ecollection-ebook",),
    )
    keys = {rule.key for rule in rules}

    assert "folio-new-load-forbidden-001" in keys
    assert "folio-ebook-required-655" in keys
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
pytest tests/test_folio_profile_db.py -q
```

Expected: FAIL with `ImportError` or `AttributeError` because `folio_profiles` does not exist.

- [ ] **Step 3: Add schema migration and profile module**

In `marcedit_web/lib/db.py`:

```python
SCHEMA_VERSION = 11
```

In `init_schema()` after `_migrate_to_v10(conn)`:

```python
            if current_version < 11:
                _migrate_to_v11(conn)
            _seed_folio_profiles(conn)
```

Add below `_migrate_to_v10`:

```python
def _migrate_to_v11(conn: sqlite3.Connection) -> None:
    """Add configurable FOLIO profile/rule storage (TASK-148)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS folio_profiles (
            key         TEXT PRIMARY KEY,
            label       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_addon    INTEGER NOT NULL DEFAULT 0,
            enabled     INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS folio_rules (
            key              TEXT PRIMARY KEY,
            profile_key      TEXT NOT NULL,
            label            TEXT NOT NULL,
            severity         TEXT NOT NULL CHECK(severity IN ('error','warning','info')),
            target_json      TEXT NOT NULL,
            requirement_json TEXT NOT NULL,
            fix_json         TEXT NOT NULL DEFAULT '{}',
            enabled          INTEGER NOT NULL DEFAULT 1,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            FOREIGN KEY(profile_key) REFERENCES folio_profiles(key) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_folio_rules_profile ON folio_rules(profile_key)")
```

Add below `_migrate_to_v11`:

```python
def _seed_folio_profiles(conn: sqlite3.Connection) -> None:
    """Seed default FOLIO profiles and rules without overwriting local edits."""
    import json

    now = _utc_now_iso()
    profiles = [
        (
            "folio-new-instance",
            "FOLIO - New Instance/SRS load",
            "Checks records before creating new FOLIO Instance and MARC SRS records.",
            0,
        ),
        (
            "folio-round-trip",
            "FOLIO - Round-trip Instance/SRS",
            "Checks records that must preserve their existing FOLIO Instance/SRS link.",
            0,
        ),
        (
            "folio-ecollection-ebook",
            "FOLIO - E-collection ebook",
            "Adds e-collection ebook standards to the selected FOLIO workflow.",
            1,
        ),
    ]
    for key, label, description, is_addon in profiles:
        conn.execute(
            "INSERT OR IGNORE INTO folio_profiles"
            "(key, label, description, is_addon, enabled, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 1, ?, ?)",
            (key, label, description, is_addon, now, now),
        )

    rules = [
        (
            "folio-new-load-forbidden-001",
            "folio-new-instance",
            "001 must be absent for new FOLIO Instance/SRS loads",
            "warning",
            {"kind": "field", "tag": "001"},
            {"kind": "forbidden"},
            {"operation": "remove_field", "tag": "001"},
        ),
        (
            "folio-roundtrip-required-001",
            "folio-round-trip",
            "001 must be present when round-tripping FOLIO Instance/SRS records",
            "error",
            {"kind": "field", "tag": "001"},
            {"kind": "required"},
            {"operation": "none"},
        ),
        (
            "folio-ebook-required-655",
            "folio-ecollection-ebook",
            "Electronic books genre/form term should be present",
            "warning",
            {"kind": "field", "tag": "655", "indicators": [" ", "7"], "subfields": {"a": "Electronic books.", "2": "local"}},
            {"kind": "field_with_subfields"},
            {"operation": "add_field", "tag": "655", "indicators": [" ", "7"], "subfields": [["a", "Electronic books."], ["2", "local"]]},
        ),
    ]
    for key, profile_key, label, severity, target, requirement, fix in rules:
        conn.execute(
            "INSERT OR IGNORE INTO folio_rules"
            "(key, profile_key, label, severity, target_json, requirement_json,"
            " fix_json, enabled, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (
                key,
                profile_key,
                label,
                severity,
                json.dumps(target, sort_keys=True),
                json.dumps(requirement, sort_keys=True),
                json.dumps(fix, sort_keys=True),
                now,
                now,
            ),
        )
```

Create `marcedit_web/lib/folio_profiles.py`:

```python
"""Configurable FOLIO profile rules and safe fixes (TASK-148)."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from . import db


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


def list_profiles() -> list[FolioProfile]:
    db.init_schema()
    with db.connect() as conn:
        rows = list(conn.execute(
            "SELECT * FROM folio_profiles WHERE enabled = 1 ORDER BY is_addon, label"
        ))
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
        rows = list(conn.execute(
            f"SELECT * FROM folio_rules"
            f" WHERE enabled = 1 AND profile_key IN ({placeholders})"
            f" ORDER BY profile_key, key",
            keys,
        ))
    return [_rule_from_row(row) for row in rows]


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
```

- [ ] **Step 4: Run tests to verify green**

Run:

```bash
pytest tests/test_folio_profile_db.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add marcedit_web/lib/db.py marcedit_web/lib/folio_profiles.py tests/test_folio_profile_db.py
git commit -m "Add FOLIO profile storage"
```

---

### Task 2: Pure FOLIO Rule Evaluation

**Files:**
- Modify: `marcedit_web/lib/folio_profiles.py`
- Test: `tests/test_folio_profiles.py`

**Interfaces:**
- Consumes: `FolioRule`
- Produces: `FolioContext(profile_key: str, addons: tuple[str, ...] = (), container_code: str = "", institution_suffix: str = "", score_loading: bool = False, use_949: bool = False)`
- Produces: `FolioIssue(issue: Issue, rule_key: str, fix_available: bool)`
- Produces: `evaluate_record(record: pymarc.Record, rules: list[FolioRule], context: FolioContext, *, record_index: int = 1) -> list[FolioIssue]`
- Produces: `evaluate_records(records: Iterable[pymarc.Record], rules: list[FolioRule], context: FolioContext) -> list[FolioIssue]`

- [ ] **Step 1: Write failing evaluator tests**

Add `tests/test_folio_profiles.py`:

```python
from __future__ import annotations

from pymarc import Field, Subfield

from marcedit_web.lib import folio_profiles


def _rules(*keys):
    all_rules = folio_profiles.default_rules_for_tests()
    return [rule for rule in all_rules if rule.key in set(keys)]


def test_new_load_flags_001_with_safe_fix(make_record):
    """New FOLIO Instance/SRS loads must not carry a source 001."""
    record = make_record()

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-new-load-forbidden-001"),
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert [item.issue.code for item in issues] == ["folio-new-load-forbidden-001"]
    assert issues[0].fix_available is True
    assert issues[0].issue.record_index == 1


def test_roundtrip_flags_missing_001_without_fix(make_record):
    """Round-trip records need 001 because it preserves the Instance/SRS link."""
    record = make_record(with_001=False)

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-roundtrip-required-001"),
        folio_profiles.FolioContext(profile_key="folio-round-trip"),
    )

    assert [item.issue.code for item in issues] == ["folio-roundtrip-required-001"]
    assert issues[0].fix_available is False
    assert issues[0].issue.severity == "error"


def test_ebook_profile_flags_missing_655_with_safe_fix(make_record):
    """The ebook add-on can add the configured local Electronic books term."""
    record = make_record()

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-ebook-required-655"),
        folio_profiles.FolioContext(
            profile_key="folio-new-instance",
            addons=("folio-ecollection-ebook",),
        ),
    )

    assert [item.issue.code for item in issues] == ["folio-ebook-required-655"]
    assert issues[0].fix_available is True


def test_008_byte_29_rejects_government_document_values(make_record):
    """008 byte 29 values s/z/o are unsafe for EDS display."""
    record = make_record()
    data = list(record["008"].data)
    data[29] = "s"
    record["008"].data = "".join(data)

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-008-byte-29-not-govdoc"),
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert [item.issue.code for item in issues] == ["folio-008-byte-29-not-govdoc"]
    assert issues[0].fix_available is False


def test_loading_path_accepts_valid_949(make_record):
    """A complete 949 path satisfies the either/or FOLIO loading-path rule."""
    record = make_record()
    record.add_field(Field(
        tag="949",
        indicators=["\\", "\\"],
        subfields=[
            Subfield("u", "https://example.test/book"),
            Subfield("y", "Connect to resource"),
            Subfield("t", "ONLINE"),
            Subfield("p", "EBOOK"),
            Subfield("h", "EBOOK"),
            Subfield("l", "elec"),
            Subfield("b", "barcode-SC"),
            Subfield("m", "sc"),
        ],
    ))

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-loading-path-required"),
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert issues == []


def test_barcode_suffix_rule_uses_configured_suffix(make_record):
    """949 $b must end in the configured institution suffix."""
    record = make_record()
    record.add_field(Field(
        tag="949",
        indicators=["\\", "\\"],
        subfields=[Subfield("b", "barcode-XX")],
    ))

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-949-barcode-suffix"),
        folio_profiles.FolioContext(
            profile_key="folio-new-instance",
            institution_suffix="SC",
        ),
    )

    assert [item.issue.code for item in issues] == ["folio-949-barcode-suffix"]
    assert issues[0].fix_available is True
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
pytest tests/test_folio_profiles.py -q
```

Expected: FAIL with missing `default_rules_for_tests`, `FolioContext`, or `evaluate_record`.

- [ ] **Step 3: Implement evaluator and add remaining seeded rule definitions**

In `marcedit_web/lib/folio_profiles.py`, add imports:

```python
from dataclasses import dataclass
from typing import Iterable

import pymarc

from .errors import Issue, make_record_issue
```

Add dataclasses:

```python
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
```

Add module-level defaults:

```python
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
        target={"kind": "field", "tag": "655", "indicators": [" ", "7"], "subfields": {"a": "Electronic books.", "2": "local"}},
        requirement={"kind": "field_with_subfields"},
        fix={"operation": "add_field", "tag": "655", "indicators": [" ", "7"], "subfields": [["a", "Electronic books."], ["2", "local"]]},
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
        requirement={"kind": "suffix_from_context", "context_key": "institution_suffix"},
        fix={"operation": "normalize_barcode_suffix", "tag": "949", "subfield": "b"},
        enabled=True,
    ),
)
```

Add helper:

```python
def default_rules_for_tests() -> list[FolioRule]:
    return list(_DEFAULT_RULES)
```

Add evaluator:

```python
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
            out.append(FolioIssue(
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
            ))
    return out
```

Add support helpers:

```python
def _rule_is_violated(record: pymarc.Record, rule: FolioRule, context: FolioContext) -> bool:
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
        return any(not value.endswith(suffix) for value in _subfield_values(record, tag, str(target["subfield"])))
    return False


def _fix_available(record: pymarc.Record, rule: FolioRule, context: FolioContext) -> bool:
    operation = rule.fix.get("operation", "none")
    if operation == "remove_field":
        return record.get(str(rule.fix.get("tag", ""))) is not None
    if operation == "add_field":
        return True
    if operation == "normalize_barcode_suffix":
        suffix = _normalized_suffix(context.institution_suffix)
        values = _subfield_values(record, str(rule.fix.get("tag", "")), str(rule.fix.get("subfield", "")))
        return bool(suffix and any(value.strip() for value in values))
    return False
```

Add MARC helpers:

```python
def _identifier(record: pymarc.Record) -> str | None:
    f001 = record.get("001")
    if f001 is not None and getattr(f001, "data", None):
        return f001.data
    for field in record.get_fields("035"):
        values = field.get_subfields("a")
        if values:
            return values[0]
    return None


def _has_field_with_subfields(record: pymarc.Record, target: dict[str, object]) -> bool:
    tag = str(target["tag"])
    expected = dict(target.get("subfields", {}))
    indicators = target.get("indicators")
    for field in record.get_fields(tag):
        if indicators is not None and list(field.indicators) != list(indicators):
            continue
        if all(expected_value in field.get_subfields(code) for code, expected_value in expected.items()):
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
        codes = {subfield.code for subfield in field.subfields if (subfield.value or "").strip()}
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
    return rule.fix.get("operation") in {"remove_field", "add_field", "normalize_barcode_suffix"}
```

- [ ] **Step 4: Run evaluator tests**

Run:

```bash
pytest tests/test_folio_profiles.py -q
```

Expected: PASS.

- [ ] **Step 5: Run storage tests**

Run:

```bash
pytest tests/test_folio_profile_db.py tests/test_folio_profiles.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add marcedit_web/lib/folio_profiles.py tests/test_folio_profiles.py
git commit -m "Add FOLIO profile evaluator"
```

---

### Task 3: Safe Fix Planning and Record-Level Application

**Files:**
- Modify: `marcedit_web/lib/folio_profiles.py`
- Test: `tests/test_folio_profile_fixes.py`

**Interfaces:**
- Consumes: `FolioRule`, `FolioContext`, `evaluate_record`
- Produces: `FolioFixPlan(rule_key: str, record_index: int, label: str, before: str, after: str, operation: str)`
- Produces: `plan_record_fixes(record: pymarc.Record, rules: list[FolioRule], context: FolioContext, *, record_index: int = 1) -> list[FolioFixPlan]`
- Produces: `apply_record_fix(record: pymarc.Record, rule: FolioRule, context: FolioContext) -> pymarc.Record`

- [ ] **Step 1: Write failing fix tests**

Add `tests/test_folio_profile_fixes.py`:

```python
from __future__ import annotations

from pymarc import Field, Subfield

from marcedit_web.lib import folio_profiles


def _rule(key):
    return next(rule for rule in folio_profiles.default_rules_for_tests() if rule.key == key)


def test_apply_new_load_001_fix_removes_only_001(make_record):
    """The new-load 001 safe fix deletes the forbidden control field only."""
    record = make_record()
    rule = _rule("folio-new-load-forbidden-001")

    updated = folio_profiles.apply_record_fix(
        record,
        rule,
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert updated.get("001") is None
    assert updated.get("245") is not None


def test_apply_ebook_655_fix_adds_configured_field(make_record):
    """The ebook safe fix adds the exact configured local 655 field."""
    record = make_record()
    rule = _rule("folio-ebook-required-655")

    updated = folio_profiles.apply_record_fix(
        record,
        rule,
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    field = updated.get_fields("655")[0]
    assert list(field.indicators) == [" ", "7"]
    assert field.get_subfields("a") == ["Electronic books."]
    assert field.get_subfields("2") == ["local"]


def test_apply_barcode_suffix_fix_replaces_existing_suffix(make_record):
    """The barcode suffix fix preserves the stem and applies the configured code."""
    record = make_record()
    record.add_field(Field(
        tag="949",
        indicators=["\\", "\\"],
        subfields=[Subfield("b", "vendor123-XX")],
    ))
    rule = _rule("folio-949-barcode-suffix")

    updated = folio_profiles.apply_record_fix(
        record,
        rule,
        folio_profiles.FolioContext(
            profile_key="folio-new-instance",
            institution_suffix="SC",
        ),
    )

    assert updated["949"].get_subfields("b") == ["vendor123-SC"]


def test_plan_record_fixes_reports_before_after_without_mutating(make_record):
    """Preview planning must not mutate records before confirmation."""
    record = make_record()
    rules = [_rule("folio-new-load-forbidden-001")]

    plans = folio_profiles.plan_record_fixes(
        record,
        rules,
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
        record_index=3,
    )

    assert record.get("001") is not None
    assert len(plans) == 1
    assert plans[0].record_index == 3
    assert plans[0].rule_key == "folio-new-load-forbidden-001"
    assert "=001" in plans[0].before
    assert "=001" not in plans[0].after
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
pytest tests/test_folio_profile_fixes.py -q
```

Expected: FAIL with missing `apply_record_fix` or `plan_record_fixes`.

- [ ] **Step 3: Implement safe fix planning and application**

In `marcedit_web/lib/folio_profiles.py`, add imports:

```python
import copy

from pymarc import Field, Subfield

from . import mrk_writer
```

Add dataclass:

```python
@dataclass(frozen=True)
class FolioFixPlan:
    rule_key: str
    record_index: int
    label: str
    before: str
    after: str
    operation: str
```

Add functions:

```python
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
            plans.append(FolioFixPlan(
                rule_key=rule.key,
                record_index=record_index,
                label=rule.label,
                before=before,
                after=after,
                operation=str(rule.fix.get("operation", "none")),
            ))
    return plans


def apply_record_fix(
    record: pymarc.Record,
    rule: FolioRule,
    context: FolioContext,
) -> pymarc.Record:
    updated = copy.deepcopy(record)
    operation = rule.fix.get("operation", "none")
    if operation == "remove_field":
        for field in list(updated.get_fields(str(rule.fix["tag"]))):
            updated.remove_field(field)
        return updated
    if operation == "add_field":
        if not _has_field_with_subfields(updated, rule.target):
            updated.add_field(_field_from_fix(rule.fix))
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
```

Add helpers:

```python
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


def _normalize_subfield_suffix(record: pymarc.Record, *, tag: str, code: str, suffix: str) -> None:
    if not suffix:
        return
    for field in record.get_fields(tag):
        for subfield in field.subfields:
            if subfield.code != code:
                continue
            value = (subfield.value or "").strip()
            if not value:
                continue
            stem = value.rsplit("-", 1)[0] if "-" in value else value
            subfield.value = f"{stem}{suffix}"
```

- [ ] **Step 4: Run fix tests**

Run:

```bash
pytest tests/test_folio_profile_fixes.py -q
```

Expected: PASS.

- [ ] **Step 5: Run all FOLIO pure-module tests**

Run:

```bash
pytest tests/test_folio_profile_db.py tests/test_folio_profiles.py tests/test_folio_profile_fixes.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add marcedit_web/lib/folio_profiles.py tests/test_folio_profile_fixes.py
git commit -m "Add FOLIO safe fix planning"
```

---

### Task 4: Complete Local FOLIO Standards Coverage

**Files:**
- Modify: `marcedit_web/lib/folio_profiles.py`
- Modify: `marcedit_web/lib/db.py`
- Test: `tests/test_folio_profiles.py`
- Test: `tests/test_folio_profile_fixes.py`

**Interfaces:**
- Consumes: `FolioContext.container_code`, `FolioContext.institution_suffix`, and existing evaluator/fix helpers.
- Extends: `default_rules_for_tests()` and `_seed_folio_profiles()` with rules for `035`, `506`, `710`, `830`, and detailed `949` requirements.

- [ ] **Step 1: Add failing standards coverage tests**

Append to `tests/test_folio_profiles.py`:

```python
def test_configured_container_code_flags_missing_035_with_fix(make_record):
    """Configured Five Colleges container code should produce a safe 035 fix."""
    record = make_record()

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-required-035-container"),
        folio_profiles.FolioContext(
            profile_key="folio-new-instance",
            container_code="FC-ABC",
        ),
    )

    assert [item.issue.code for item in issues] == ["folio-required-035-container"]
    assert issues[0].fix_available is True


def test_506_multi_institution_rule_is_check_only(make_record):
    """506 is required for multi-institution loads but needs cataloger review."""
    record = make_record()

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-multi-institution-506"),
        folio_profiles.FolioContext(
            profile_key="folio-new-instance",
            multi_institution=True,
        ),
    )

    assert [item.issue.code for item in issues] == ["folio-multi-institution-506"]
    assert issues[0].fix_available is False


def test_configured_710_and_830_recommendations_have_safe_fixes(make_record):
    """Configured local collection access points can be added deterministically."""
    record = make_record()

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-recommended-710-local", "folio-recommended-830-local"),
        folio_profiles.FolioContext(
            profile_key="folio-new-instance",
            collection_name="Five Colleges test collection",
        ),
    )

    assert {item.issue.code for item in issues} == {
        "folio-recommended-710-local",
        "folio-recommended-830-local",
    }
    assert all(item.fix_available for item in issues)


def test_incomplete_949_lists_missing_required_subfields(make_record):
    """The 949 path must call out missing configured required subfields."""
    record = make_record()
    record.add_field(Field(
        tag="949",
        indicators=["\\", "\\"],
        subfields=[Subfield("u", "https://example.test/book")],
    ))

    issues = folio_profiles.evaluate_record(
        record,
        _rules("folio-949-required-subfields"),
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert [item.issue.code for item in issues] == ["folio-949-required-subfields"]
    assert "$y" in issues[0].issue.message
```

Append to `tests/test_folio_profile_fixes.py`:

```python
def test_apply_035_container_fix_adds_configured_field(make_record):
    """The 035 container-code fix writes the configured local code."""
    record = make_record()
    rule = _rule("folio-required-035-container")

    updated = folio_profiles.apply_record_fix(
        record,
        rule,
        folio_profiles.FolioContext(
            profile_key="folio-new-instance",
            container_code="FC-ABC",
        ),
    )

    field = updated.get_fields("035")[0]
    assert list(field.indicators) == ["9", "\\"]
    assert field.get_subfields("a") == ["FC-ABC"]
```

- [ ] **Step 2: Run standards tests to verify red**

Run:

```bash
pytest tests/test_folio_profiles.py::test_configured_container_code_flags_missing_035_with_fix tests/test_folio_profiles.py::test_506_multi_institution_rule_is_check_only tests/test_folio_profiles.py::test_configured_710_and_830_recommendations_have_safe_fixes tests/test_folio_profiles.py::test_incomplete_949_lists_missing_required_subfields tests/test_folio_profile_fixes.py::test_apply_035_container_fix_adds_configured_field -q
```

Expected: FAIL because the extra context fields and rules do not exist.

- [ ] **Step 3: Extend `FolioContext`**

In `marcedit_web/lib/folio_profiles.py`, change `FolioContext` to:

```python
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
```

- [ ] **Step 4: Add standards rules to `_DEFAULT_RULES`**

Append these `FolioRule` entries to `_DEFAULT_RULES` in `marcedit_web/lib/folio_profiles.py`:

```python
    FolioRule(
        key="folio-required-035-container",
        profile_key="folio-new-instance",
        label="035 9\\ container code should be present",
        severity="warning",
        target={"kind": "field", "tag": "035", "indicators": ["9", "\\"], "subfields": {"a": "{container_code}"}},
        requirement={"kind": "field_with_context_subfields", "context_key": "container_code"},
        fix={"operation": "add_context_field", "tag": "035", "indicators": ["9", "\\"], "subfields": [["a", "{container_code}"]]},
        enabled=True,
    ),
    FolioRule(
        key="folio-multi-institution-506",
        profile_key="folio-new-instance",
        label="506 1\\ should be present for multi-institution loads",
        severity="warning",
        target={"kind": "field", "tag": "506", "indicators": ["1", "\\"]},
        requirement={"kind": "required_when_context_true", "context_key": "multi_institution"},
        fix={"operation": "none"},
        enabled=True,
    ),
    FolioRule(
        key="folio-recommended-710-local",
        profile_key="folio-new-instance",
        label="710 2\\ local collection access point is recommended",
        severity="info",
        target={"kind": "field", "tag": "710", "indicators": ["2", "\\"], "subfields": {"a": "{collection_name}", "2": "local"}},
        requirement={"kind": "field_with_context_subfields", "context_key": "collection_name"},
        fix={"operation": "add_context_field", "tag": "710", "indicators": ["2", "\\"], "subfields": [["a", "{collection_name}"], ["2", "local"]]},
        enabled=True,
    ),
    FolioRule(
        key="folio-recommended-830-local",
        profile_key="folio-new-instance",
        label="830 \\0 local series access point is recommended",
        severity="info",
        target={"kind": "field", "tag": "830", "indicators": ["\\", "0"], "subfields": {"a": "{collection_name}", "2": "local"}},
        requirement={"kind": "field_with_context_subfields", "context_key": "collection_name"},
        fix={"operation": "add_context_field", "tag": "830", "indicators": ["\\", "0"], "subfields": [["a", "{collection_name}"], ["2", "local"]]},
        enabled=True,
    ),
    FolioRule(
        key="folio-949-required-subfields",
        profile_key="folio-new-instance",
        label="949 field is missing required FOLIO load subfields",
        severity="warning",
        target={"kind": "949_required_subfields", "required": ["u", "y", "t", "p", "l", "b", "m"]},
        requirement={"kind": "949_required_subfields"},
        fix={"operation": "none"},
        enabled=True,
    ),
```

- [ ] **Step 5: Extend evaluator helper logic**

In `_rule_is_violated`, add:

```python
    if kind == "field_with_context_subfields":
        context_value = _context_value(context, str(requirement["context_key"]))
        if not context_value:
            return False
        return not _has_field_with_subfields(record, _resolve_context_tokens(target, context))
    if kind == "required_when_context_true":
        if not bool(_context_value(context, str(requirement["context_key"]))):
            return False
        return record.get(tag) is None
    if kind == "949_required_subfields":
        return _missing_949_subfields(record) != []
```

Change the `either_group_present` branch to continue using `_has_valid_949(record)`.

Add helpers:

```python
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
```

In `_suggestion_for`, for `folio-949-required-subfields`, return:

```python
    if rule.key == "folio-949-required-subfields":
        return "Complete the 949 load field before loading to FOLIO."
```

In `evaluate_record`, after creating the `message`, special-case the missing
949 subfields:

```python
                    rule.label
                    if rule.key != "folio-949-required-subfields"
                    else f"{rule.label}: {', '.join(_missing_949_subfields(record))}",
```

- [ ] **Step 6: Add context-field fix operation**

In `_fix_available`, add:

```python
    if operation == "add_context_field":
        context_key = str(rule.requirement.get("context_key", ""))
        return bool(_context_value(context, context_key))
```

In `apply_record_fix`, add:

```python
    if operation == "add_context_field":
        resolved_fix = _resolve_context_tokens(rule.fix, context)
        resolved_target = _resolve_context_tokens(rule.target, context)
        if not _has_field_with_subfields(updated, resolved_target):
            updated.add_field(_field_from_fix(resolved_fix))
        return updated
```

- [ ] **Step 7: Update DB seed with all default rules**

In `marcedit_web/lib/db.py`, add the same standards rules to the local
`rules = [...]` list in `_seed_folio_profiles()`. Keep the tuple shape already
used there:

```python
(
    "folio-required-035-container",
    "folio-new-instance",
    "035 9\\ container code should be present",
    "warning",
    {"kind": "field", "tag": "035", "indicators": ["9", "\\"], "subfields": {"a": "{container_code}"}},
    {"kind": "field_with_context_subfields", "context_key": "container_code"},
    {"operation": "add_context_field", "tag": "035", "indicators": ["9", "\\"], "subfields": [["a", "{container_code}"]]},
),
(
    "folio-multi-institution-506",
    "folio-new-instance",
    "506 1\\ should be present for multi-institution loads",
    "warning",
    {"kind": "field", "tag": "506", "indicators": ["1", "\\"]},
    {"kind": "required_when_context_true", "context_key": "multi_institution"},
    {"operation": "none"},
),
(
    "folio-recommended-710-local",
    "folio-new-instance",
    "710 2\\ local collection access point is recommended",
    "info",
    {"kind": "field", "tag": "710", "indicators": ["2", "\\"], "subfields": {"a": "{collection_name}", "2": "local"}},
    {"kind": "field_with_context_subfields", "context_key": "collection_name"},
    {"operation": "add_context_field", "tag": "710", "indicators": ["2", "\\"], "subfields": [["a", "{collection_name}"], ["2", "local"]]},
),
(
    "folio-recommended-830-local",
    "folio-new-instance",
    "830 \\0 local series access point is recommended",
    "info",
    {"kind": "field", "tag": "830", "indicators": ["\\", "0"], "subfields": {"a": "{collection_name}", "2": "local"}},
    {"kind": "field_with_context_subfields", "context_key": "collection_name"},
    {"operation": "add_context_field", "tag": "830", "indicators": ["\\", "0"], "subfields": [["a", "{collection_name}"], ["2", "local"]]},
),
(
    "folio-949-required-subfields",
    "folio-new-instance",
    "949 field is missing required FOLIO load subfields",
    "warning",
    {"kind": "949_required_subfields", "required": ["u", "y", "t", "p", "l", "b", "m"]},
    {"kind": "949_required_subfields"},
    {"operation": "none"},
),
```

- [ ] **Step 8: Run standards tests**

Run:

```bash
pytest tests/test_folio_profiles.py tests/test_folio_profile_fixes.py tests/test_folio_profile_db.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add marcedit_web/lib/folio_profiles.py marcedit_web/lib/db.py tests/test_folio_profiles.py tests/test_folio_profile_fixes.py
git commit -m "Complete seeded FOLIO standards coverage"
```

---

### Task 5: Batch Preview and Store Application

**Files:**
- Modify: `marcedit_web/lib/folio_profiles.py`
- Test: `tests/test_folio_profile_fixes.py`

**Interfaces:**
- Consumes: `RecordStore.iter_records()`, `RecordStore.replace(idx, record)`
- Produces: `FolioBatchPreview(total_fixes: int, affected_records: int, by_rule: dict[str, int], samples: list[FolioFixPlan])`
- Produces: `preview_batch_fixes(records: Iterable[pymarc.Record], rules: list[FolioRule], context: FolioContext, *, sample_limit: int = 10) -> FolioBatchPreview`
- Produces: `apply_batch_fixes_to_store(store: RecordStore, rules: list[FolioRule], context: FolioContext) -> FolioBatchPreview`

- [ ] **Step 1: Add failing batch preview/application tests**

Append to `tests/test_folio_profile_fixes.py`:

```python
from marcedit_web.lib.record_store import RecordStore


def test_preview_batch_fixes_counts_without_mutating(make_record):
    """Batch preview reports compact counts and samples without changing records."""
    records = [make_record(), make_record()]
    rule = _rule("folio-new-load-forbidden-001")

    preview = folio_profiles.preview_batch_fixes(
        records,
        [rule],
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
        sample_limit=1,
    )

    assert preview.total_fixes == 2
    assert preview.affected_records == 2
    assert preview.by_rule == {"folio-new-load-forbidden-001": 2}
    assert len(preview.samples) == 1
    assert records[0].get("001") is not None


def test_apply_batch_fixes_to_store_replaces_changed_records(make_record, tmp_path):
    """Confirmed batch application mutates the disk-backed store records."""
    store = RecordStore.from_records(
        [make_record(), make_record()],
        tmp_dir=tmp_path,
        filename="sample.mrc",
    )
    rule = _rule("folio-new-load-forbidden-001")

    preview = folio_profiles.apply_batch_fixes_to_store(
        store,
        [rule],
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert preview.total_fixes == 2
    assert all(record.get("001") is None for record in store.iter_records())
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
pytest tests/test_folio_profile_fixes.py::test_preview_batch_fixes_counts_without_mutating tests/test_folio_profile_fixes.py::test_apply_batch_fixes_to_store_replaces_changed_records -q
```

Expected: FAIL with missing batch preview/application functions.

- [ ] **Step 3: Implement batch preview and store application**

In `marcedit_web/lib/folio_profiles.py`, add dataclass:

```python
@dataclass(frozen=True)
class FolioBatchPreview:
    total_fixes: int
    affected_records: int
    by_rule: dict[str, int]
    samples: list[FolioFixPlan]
```

Add functions:

```python
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
```

- [ ] **Step 4: Run batch tests**

Run:

```bash
pytest tests/test_folio_profile_fixes.py -q
```

Expected: PASS.

- [ ] **Step 5: Run record store regression tests**

Run:

```bash
pytest tests/test_record_store.py tests/test_folio_profile_fixes.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add marcedit_web/lib/folio_profiles.py tests/test_folio_profile_fixes.py
git commit -m "Add FOLIO batch safe fixes"
```

---

### Task 6: Validate Pipeline Integration

**Files:**
- Modify: `marcedit_web/render/validate.py`
- Test: `tests/test_validate_folio_profiles.py`

**Interfaces:**
- Consumes: `folio_profiles.rules_for_profile`, `folio_profiles.evaluate_records`
- Produces: `validate._folio_context_from_state() -> folio_profiles.FolioContext | None`
- Produces: `validate._compute_issues(..., folio_context: FolioContext | None = None) -> list[Issue]`

- [ ] **Step 1: Write failing Validate integration tests**

Add `tests/test_validate_folio_profiles.py`:

```python
from __future__ import annotations

from marcedit_web.lib import folio_profiles
from marcedit_web.lib.rules import RuleSet
from marcedit_web.render import validate


class _FakeStatus:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, **_kwargs):
        return None


class _FakeStore:
    def __init__(self, records):
        self._records = records

    def iter_records(self):
        return iter(self._records)


def test_compute_issues_includes_selected_folio_profile(make_record, monkeypatch):
    """Validate includes selected FOLIO profile diagnostics in its issue list."""
    monkeypatch.setattr(validate.st, "status", lambda *_args, **_kwargs: _FakeStatus())
    monkeypatch.setattr(
        validate.folio_profiles,
        "rules_for_profile",
        lambda profile_key, include_addons=(): [
            rule for rule in folio_profiles.default_rules_for_tests()
            if rule.key == "folio-new-load-forbidden-001"
        ],
    )
    store = _FakeStore([make_record()])

    issues = validate._compute_issues(
        RuleSet(),
        store,
        malformed=0,
        folio_context=folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert "folio-new-load-forbidden-001" in {issue.code for issue in issues}
```

- [ ] **Step 2: Run test to verify red**

Run:

```bash
pytest tests/test_validate_folio_profiles.py -q
```

Expected: FAIL because `_compute_issues` has no `folio_context` parameter or `validate.folio_profiles` import.

- [ ] **Step 3: Integrate FOLIO evaluation into `_compute_issues`**

In `marcedit_web/render/validate.py`, add import:

```python
    folio_profiles,
```

Change `_compute_issues` signature:

```python
def _compute_issues(
    rule_set: rules_mod.RuleSet | None,
    store,
    malformed: int,
    folio_context: folio_profiles.FolioContext | None = None,
) -> list[Issue]:
```

Before `all_issues`, add:

```python
        folio_issues: list[Issue] = []
        if folio_context is not None:
            status.update(label="Applying FOLIO profile rules...")
            profile_rules = folio_profiles.rules_for_profile(
                folio_context.profile_key,
                include_addons=folio_context.addons,
            )
            folio_results = folio_profiles.evaluate_records(
                store.iter_records() if store else iter([]),
                profile_rules,
                folio_context,
            )
            folio_issues = [result.issue for result in folio_results]
```

Change issue combination:

```python
        all_issues: list[Issue] = (
            preflight_issues + rule_issues + load_issues + folio_issues
        )
```

- [ ] **Step 4: Run Validate integration tests**

Run:

```bash
pytest tests/test_validate_folio_profiles.py tests/test_validate_load_readiness.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add marcedit_web/render/validate.py tests/test_validate_folio_profiles.py
git commit -m "Include FOLIO profiles in validation"
```

---

### Task 7: Validate UI Controls and Fix Availability Display

**Files:**
- Modify: `marcedit_web/render/validate.py`
- Test: `tests/test_validate_folio_profiles.py`

**Interfaces:**
- Consumes: `FolioContext`
- Produces: `validate._build_folio_context(profile_key: str, addon_enabled: bool, institution_suffix: str, container_code: str, collection_name: str = "", multi_institution: bool = False, score_loading: bool = False) -> FolioContext | None`
- Produces: issue table column `fix_available`

- [ ] **Step 1: Add failing helper tests**

Append to `tests/test_validate_folio_profiles.py`:

```python
def test_build_folio_context_includes_ebook_addon():
    """Validate UI helper converts selected controls into evaluator context."""
    context = validate._build_folio_context(
        profile_key="folio-new-instance",
        addon_enabled=True,
        institution_suffix="SC",
        container_code="FC123",
        score_loading=False,
    )

    assert context.profile_key == "folio-new-instance"
    assert context.addons == ("folio-ecollection-ebook",)
    assert context.institution_suffix == "SC"
    assert context.container_code == "FC123"


def test_build_folio_context_disabled_when_profile_blank():
    """Leaving the profile blank keeps Validate behavior unchanged."""
    assert validate._build_folio_context(
        profile_key="",
        addon_enabled=True,
        institution_suffix="SC",
        container_code="FC123",
        score_loading=False,
    ) is None
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
pytest tests/test_validate_folio_profiles.py::test_build_folio_context_includes_ebook_addon tests/test_validate_folio_profiles.py::test_build_folio_context_disabled_when_profile_blank -q
```

Expected: FAIL because `_build_folio_context` does not exist.

- [ ] **Step 3: Implement context helper**

In `marcedit_web/render/validate.py`, add:

```python
def _build_folio_context(
    *,
    profile_key: str,
    addon_enabled: bool,
    institution_suffix: str,
    container_code: str,
    collection_name: str = "",
    multi_institution: bool = False,
    score_loading: bool = False,
) -> folio_profiles.FolioContext | None:
    if not profile_key:
        return None
    addons = ("folio-ecollection-ebook",) if addon_enabled else ()
    return folio_profiles.FolioContext(
        profile_key=profile_key,
        addons=addons,
        container_code=container_code.strip(),
        institution_suffix=institution_suffix.strip().upper(),
        collection_name=collection_name.strip(),
        multi_institution=multi_institution,
        score_loading=score_loading,
    )
```

- [ ] **Step 4: Render FOLIO controls in `render()`**

In `render()`, before cache lookup, add:

```python
    st.subheader("FOLIO profile")
    profiles = [profile for profile in folio_profiles.list_profiles() if not profile.is_addon]
    profile_options = [""] + [profile.key for profile in profiles]
    profile_labels = {"": "No FOLIO profile"}
    profile_labels.update({profile.key: profile.label for profile in profiles})
    selected_profile = st.selectbox(
        "Profile",
        options=profile_options,
        format_func=lambda key: profile_labels.get(key, key),
        key="folio_profile_key",
    )
    addon_enabled = st.checkbox(
        "Apply e-collection ebook rules",
        value=False,
        key="folio_ebook_addon",
    )
    col_cfg1, col_cfg2, col_cfg3 = st.columns(3)
    container_code = col_cfg1.text_input(
        "Container code",
        key="folio_container_code",
    )
    institution_suffix = col_cfg2.text_input(
        "Institution suffix",
        placeholder="SC",
        key="folio_institution_suffix",
    )
    score_loading = col_cfg3.checkbox(
        "Score loading",
        value=False,
        key="folio_score_loading",
    )
    collection_name = st.text_input(
        "Collection name",
        key="folio_collection_name",
    )
    multi_institution = st.checkbox(
        "Multi-institution load",
        value=False,
        key="folio_multi_institution",
    )
    folio_context = _build_folio_context(
        profile_key=selected_profile,
        addon_enabled=addon_enabled,
        institution_suffix=institution_suffix,
        container_code=container_code,
        collection_name=collection_name,
        multi_institution=multi_institution,
        score_loading=score_loading,
    )
```

Change cache key:

```python
    cache_key = (
        "validate",
        store.revision if store else 0,
        folio_context,
    )
    all_issues = cache.get(cache_key)
    if all_issues is None:
        all_issues = _compute_issues(rule_set, store, malformed, folio_context)
        cache.clear()
        cache[cache_key] = all_issues
```

- [ ] **Step 5: Add fix availability column**

After building `issue_rows`, compute FOLIO availability:

```python
    fixable_codes: set[str] = set()
    if folio_context is not None and store is not None:
        profile_rules = folio_profiles.rules_for_profile(
            folio_context.profile_key,
            include_addons=folio_context.addons,
        )
        for item in folio_profiles.evaluate_records(
            store.iter_records(),
            profile_rules,
            folio_context,
        ):
            if item.fix_available:
                fixable_codes.add(item.issue.code)
```

Add to each issue row:

```python
            "fix_available": "yes" if i.code in fixable_codes else "",
```

Add dataframe column config:

```python
            "fix_available": st.column_config.TextColumn("Fix", width="small"),
```

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/test_validate_folio_profiles.py tests/test_validate_styling.py tests/test_validate_view_button.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add marcedit_web/render/validate.py tests/test_validate_folio_profiles.py
git commit -m "Add FOLIO profile controls to Validate"
```

---

### Task 8: Per-Record Safe Fix Action

**Files:**
- Modify: `marcedit_web/render/_record_modal.py`
- Modify: `marcedit_web/render/validate.py`
- Test: `tests/test_validate_folio_profiles.py`

**Interfaces:**
- Consumes: `folio_profiles.apply_record_fix`
- Produces: optional modal parameters:
  - `fix_label: str | None = None`
  - `on_fix=None`

- [ ] **Step 1: Add failing helper test**

Append to `tests/test_validate_folio_profiles.py`:

```python
def test_find_single_folio_fix_rule_returns_matching_rule(make_record):
    """Validate can map a selected FOLIO issue back to one safe fix rule."""
    rules = [
        rule for rule in folio_profiles.default_rules_for_tests()
        if rule.key == "folio-new-load-forbidden-001"
    ]
    rule = validate._find_single_folio_fix_rule(
        make_record(),
        "folio-new-load-forbidden-001",
        rules,
        folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert rule.key == "folio-new-load-forbidden-001"
```

- [ ] **Step 2: Run test to verify red**

Run:

```bash
pytest tests/test_validate_folio_profiles.py::test_find_single_folio_fix_rule_returns_matching_rule -q
```

Expected: FAIL because `_find_single_folio_fix_rule` does not exist.

- [ ] **Step 3: Add modal fix button extension**

In `marcedit_web/render/_record_modal.py`, change `open_record_modal` signature:

```python
def open_record_modal(
    *,
    record_index: int,
    store: RecordStore,
    extra_lines: list[tuple[str, str]] | None = None,
    highlight_tag: str | None = None,
    highlight_severity: str | None = None,
    fix_label: str | None = None,
    on_fix=None,
) -> None:
```

Before the "Edit this record" button, add:

```python
    if fix_label and on_fix is not None:
        if st.button(
            fix_label,
            key=f"_modal_fix_{record_index}_{highlight_tag or 'record'}",
            icon=":material/build:",
            use_container_width=True,
            type="primary",
        ):
            on_fix(record_index, record)
            st.rerun()
```

- [ ] **Step 4: Add Validate helper and pass callback**

In `marcedit_web/render/validate.py`, add:

```python
def _find_single_folio_fix_rule(
    record,
    issue_code: str,
    rules: list[folio_profiles.FolioRule],
    context: folio_profiles.FolioContext,
) -> folio_profiles.FolioRule | None:
    matches = []
    for item in folio_profiles.evaluate_record(record, rules, context):
        if item.issue.code == issue_code and item.fix_available:
            matches.append(next(rule for rule in rules if rule.key == item.rule_key))
    return matches[0] if len(matches) == 1 else None
```

Inside the existing `clicked and chosen` block, before `open_record_modal`, add:

```python
            fix_label = None
            on_fix = None
            if folio_context is not None and row["code"].startswith("folio-"):
                profile_rules = folio_profiles.rules_for_profile(
                    folio_context.profile_key,
                    include_addons=folio_context.addons,
                )
                current_record = store.get(record_index - 1)
                fix_rule = (
                    _find_single_folio_fix_rule(
                        current_record,
                        row["code"],
                        profile_rules,
                        folio_context,
                    )
                    if current_record is not None
                    else None
                )
                if fix_rule is not None:
                    fix_label = "Apply FOLIO safe fix"

                    def on_fix(record_no: int, record, *, _rule=fix_rule):
                        updated = folio_profiles.apply_record_fix(
                            record,
                            _rule,
                            folio_context,
                        )
                        store.replace(record_no - 1, updated)
                        st.session_state.pop("issues_cache", None)
```

Pass to `open_record_modal`:

```python
                fix_label=fix_label,
                on_fix=on_fix,
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_validate_folio_profiles.py tests/test_view_render.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add marcedit_web/render/_record_modal.py marcedit_web/render/validate.py tests/test_validate_folio_profiles.py
git commit -m "Add per-record FOLIO safe fixes"
```

---

### Task 9: Batch Preview and Confirm UI

**Files:**
- Modify: `marcedit_web/render/validate.py`
- Test: `tests/test_validate_folio_profiles.py`

**Interfaces:**
- Consumes: `folio_profiles.preview_batch_fixes`
- Consumes: `folio_profiles.apply_batch_fixes_to_store`
- Produces: `validate._preview_to_rows(preview: FolioBatchPreview) -> list[dict[str, object]]`

- [ ] **Step 1: Add failing preview row test**

Append to `tests/test_validate_folio_profiles.py`:

```python
def test_preview_to_rows_formats_rule_counts():
    """Batch preview summaries render as stable table rows."""
    preview = folio_profiles.FolioBatchPreview(
        total_fixes=3,
        affected_records=2,
        by_rule={"folio-new-load-forbidden-001": 2, "folio-ebook-required-655": 1},
        samples=[],
    )

    rows = validate._preview_to_rows(preview)

    assert rows == [
        {"rule": "folio-ebook-required-655", "fixes": 1},
        {"rule": "folio-new-load-forbidden-001", "fixes": 2},
    ]
```

- [ ] **Step 2: Run test to verify red**

Run:

```bash
pytest tests/test_validate_folio_profiles.py::test_preview_to_rows_formats_rule_counts -q
```

Expected: FAIL because `_preview_to_rows` does not exist.

- [ ] **Step 3: Add preview helper**

In `marcedit_web/render/validate.py`, add:

```python
def _preview_to_rows(preview: folio_profiles.FolioBatchPreview) -> list[dict[str, object]]:
    return [
        {"rule": rule, "fixes": count}
        for rule, count in sorted(preview.by_rule.items())
    ]
```

- [ ] **Step 4: Render batch preview controls**

After issue table and before record view widget, add:

```python
    if folio_context is not None and store is not None:
        profile_rules = folio_profiles.rules_for_profile(
            folio_context.profile_key,
            include_addons=folio_context.addons,
        )
        if st.button(
            "Preview FOLIO safe fixes",
            key="folio_preview_safe_fixes",
            icon=":material/rule_settings:",
        ):
            st.session_state["folio_safe_fix_preview"] = folio_profiles.preview_batch_fixes(
                store.iter_records(),
                profile_rules,
                folio_context,
            )
            st.rerun()
        preview = st.session_state.get("folio_safe_fix_preview")
        if preview is not None:
            st.subheader("FOLIO safe-fix preview")
            st.caption(
                f"{preview.total_fixes} fix(es) across "
                f"{preview.affected_records} record(s)."
            )
            st.dataframe(
                pd.DataFrame(_preview_to_rows(preview)),
                hide_index=True,
                use_container_width=True,
            )
            if preview.samples:
                with st.expander("Preview samples", expanded=False):
                    for sample in preview.samples:
                        st.markdown(f"**Record #{sample.record_index}: {sample.label}**")
                        st.code(sample.before, language=None)
                        st.code(sample.after, language=None)
            if st.button(
                "Apply previewed FOLIO fixes",
                key="folio_apply_safe_fixes",
                type="primary",
                icon=":material/check:",
            ):
                folio_profiles.apply_batch_fixes_to_store(
                    store,
                    profile_rules,
                    folio_context,
                )
                st.session_state.pop("folio_safe_fix_preview", None)
                st.session_state.pop("issues_cache", None)
                st.success("FOLIO safe fixes applied.")
                st.rerun()
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_validate_folio_profiles.py tests/test_validate_styling.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add marcedit_web/render/validate.py tests/test_validate_folio_profiles.py
git commit -m "Add batch FOLIO safe fix preview"
```

---

### Task 10: Provenance Snapshot Integration and Regression Cleanup

**Files:**
- Modify: `marcedit_web/render/validate.py`
- Modify: `.tickets/TASK-148-folio-rule-profiles.md`
- Test: existing suite slice

**Interfaces:**
- Consumes: `snapshot_actions.record_edit_snapshot`
- Consumes: `snapshot_actions.staged_store_path`
- Consumes: `session.current_user_id()`, `st.session_state.get("current_job_id")`

- [ ] **Step 1: Add snapshot helper in Validate**

In `marcedit_web/render/validate.py`, add imports:

```python
    snapshot_actions,
```

Add helper:

```python
def _record_folio_snapshot(store, *, label: str, summary: dict[str, object]) -> None:
    with snapshot_actions.staged_store_path(store) as after_path:
        snapshot_actions.record_edit_snapshot(
            job_id=st.session_state.get("current_job_id"),
            user_email=session.current_user_id(),
            label=label,
            after_path=after_path,
            record_index=None,
            source="folio-safe-fix",
            summary=summary,
        )
```

- [ ] **Step 2: Call snapshot helper after fixes**

In the per-record callback after `store.replace(...)`, add:

```python
                        _record_folio_snapshot(
                            store,
                            label="FOLIO safe fix",
                            summary={
                                "rule": _rule.key,
                                "record_index": record_no,
                                "mode": "single-record",
                            },
                        )
```

In the batch apply block, capture result and add:

```python
                applied = folio_profiles.apply_batch_fixes_to_store(
                    store,
                    profile_rules,
                    folio_context,
                )
                _record_folio_snapshot(
                    store,
                    label="FOLIO batch safe fixes",
                    summary={
                        "mode": "batch",
                        "total_fixes": applied.total_fixes,
                        "affected_records": applied.affected_records,
                        "by_rule": applied.by_rule,
                    },
                )
```

- [ ] **Step 3: Mark ticket implementation status**

In `.tickets/TASK-148-folio-rule-profiles.md`, keep status as `In-Progress` until the full verification step passes. Do not mark complete yet.

- [ ] **Step 4: Run focused regression suite**

Run:

```bash
pytest tests/test_folio_profile_db.py tests/test_folio_profiles.py tests/test_folio_profile_fixes.py tests/test_validate_folio_profiles.py tests/test_validate_load_readiness.py tests/test_validate_view_button.py tests/test_view_render.py tests/test_record_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add marcedit_web/render/validate.py .tickets/TASK-148-folio-rule-profiles.md
git commit -m "Record FOLIO safe fix provenance"
```

---

## Final Verification

- [ ] Run `pytest -q`.
- [ ] If Docker verification is available, run `docker compose run --rm marcedit-web pytest -q`.
- [ ] Start the app with `docker compose up -d` or the local project command used in this repo.
- [ ] Upload a small MARC file containing `001`.
- [ ] Open Validate.
- [ ] Select `FOLIO - New Instance/SRS load`.
- [ ] Confirm the issue table includes `folio-new-load-forbidden-001`.
- [ ] Open a record issue and apply the per-record safe fix.
- [ ] Confirm `001` is gone from that record and validation cache refreshes.
- [ ] Re-upload/reset the sample.
- [ ] Preview batch safe fixes.
- [ ] Confirm preview reports affected records and sample before/after snippets.
- [ ] Apply batch fixes.
- [ ] Confirm Validate no longer shows `folio-new-load-forbidden-001` for changed records.
- [ ] Confirm History shows a FOLIO safe-fix snapshot when a current job is active.
- [ ] Mark `.tickets/TASK-148-folio-rule-profiles.md` status `Completed`.
- [ ] Commit the ticket completion.

## Self-Review Notes

- Spec coverage: storage, seeded profiles, selected workflow context, ebook add-on, `001`, `035`, `506`, `655`, `710`, `830`, loading-path, `949`, issue codes, safe fix policy, batch preview, per-record fixes, and provenance are each assigned to tasks.
- Scope held: no FOLIO API work and no silent export normalization.
- Implementation risk: Task 6's fix-availability column recomputes FOLIO evaluation for display; if this is slow on very large files, replace it during execution with a per-record/code lookup built during `_compute_issues`.
