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
