"""Transparent deterministic RDA-oriented MARC operations (TASK-181)."""

from __future__ import annotations

from dataclasses import dataclass

from pymarc import Field, Record, Subfield


@dataclass(frozen=True)
class MaterialMapping:
    name: str
    content: tuple[str, str]
    media: tuple[str, str]
    carrier: tuple[str, str]


MATERIAL_MAPPINGS = {
    "text": MaterialMapping("text", ("text", "txt"), ("computer", "c"), ("online resource", "cr")),
    "computer": MaterialMapping("computer", ("computer program", "cop"), ("computer", "c"), ("online resource", "cr")),
    "audio": MaterialMapping("audio", ("spoken word", "spw"), ("audio", "s"), ("online resource", "cr")),
    "video": MaterialMapping("video", ("two-dimensional moving image", "tdi"), ("video", "v"), ("online resource", "cr")),
    "map": MaterialMapping("map", ("cartographic image", "cri"), ("computer", "c"), ("online resource", "cr")),
}


def classify_material(record: Record) -> tuple[str | None, str]:
    """Classify from Leader/007 evidence; return ``(type, evidence)``."""
    leader_type = str(record.leader)[6]
    seven = record.get("007")
    seven_data = str(getattr(seven, "data", "") or "")
    if leader_type in {"e", "f"}:
        return "map", f"Leader/06={leader_type}"
    if leader_type == "g" or seven_data.startswith("v"):
        return "video", f"Leader/06={leader_type}, 007/00={seven_data[:1] or '?'}"
    if leader_type in {"i", "j"} or seven_data.startswith("s"):
        return "audio", f"Leader/06={leader_type}, 007/00={seven_data[:1] or '?'}"
    if leader_type == "m":
        return "computer", "Leader/06=m"
    if leader_type in {"a", "t"}:
        return "text", f"Leader/06={leader_type}"
    return None, f"Leader/06={leader_type!r} has no unambiguous mapping"


def _fields_for(mapping: MaterialMapping) -> list[Field]:
    return [
        Field(tag="336", indicators=[" ", " "], subfields=[Subfield("a", mapping.content[0]), Subfield("b", mapping.content[1]), Subfield("2", "rdacontent")]),
        Field(tag="337", indicators=[" ", " "], subfields=[Subfield("a", mapping.media[0]), Subfield("b", mapping.media[1]), Subfield("2", "rdamedia")]),
        Field(tag="338", indicators=[" ", " "], subfields=[Subfield("a", mapping.carrier[0]), Subfield("b", mapping.carrier[1]), Subfield("2", "rdacarrier")]),
    ]


def apply_material_classification(
    record: Record,
    *,
    mode: str = "classify",
    fixed_material: str = "text",
    existing_field_action: str = "preserve",
) -> dict:
    """Add deterministic 336/337/338 fields and report evidence."""
    if mode == "classify":
        material, evidence = classify_material(record)
    elif mode == "fixed":
        material, evidence = fixed_material, "cataloger-selected fixed mapping"
    else:
        raise ValueError("material classification mode must be classify or fixed")
    if material is None:
        raise ValueError(f"ambiguous material classification: {evidence}")
    if material not in MATERIAL_MAPPINGS:
        raise ValueError(f"material mapping is not supported: {material}")
    proposed = _fields_for(MATERIAL_MAPPINGS[material])
    changed = 0
    for field in proposed:
        existing = record.get_fields(field.tag)
        if existing and existing_field_action == "preserve":
            continue
        if existing:
            record.remove_fields(field.tag)
        record.add_ordered_field(field)
        changed += 1
    return {"material": material, "evidence": evidence, "changed_fields": changed}


def mark_rda(record: Record) -> bool:
    """Ensure the first 040 has ``$e rda`` without duplicating it."""
    field = record.get("040")
    if field is None:
        record.add_ordered_field(Field(tag="040", indicators=[" ", " "], subfields=[Subfield("e", "rda")]))
        return True
    if "rda" in field.get_subfields("e"):
        return False
    field.subfields.append(Subfield("e", "rda"))
    return True


def remove_gmd(record: Record, value: str = "") -> int:
    """Remove 245 $h values, optionally only an exact value."""
    removed = 0
    for field in record.get_fields("245"):
        kept = []
        for subfield in field.subfields:
            if subfield.code == "h" and (not value or subfield.value == value):
                removed += 1
            else:
                kept.append(subfield)
        field.subfields = kept
    return removed


ABBREVIATION_MAP = {"p.": "pages", "ill.": "illustrations", "col.": "color"}


def expand_abbreviations(record: Record, tag: str = "300", code: str = "a") -> int:
    changed = 0
    for field in record.get_fields(tag):
        for index, subfield in enumerate(field.subfields):
            if subfield.code != code:
                continue
            value = subfield.value
            for source, target in ABBREVIATION_MAP.items():
                value = value.replace(source, target)
            if value != subfield.value:
                field.subfields[index] = Subfield(code, value)
                changed += 1
    return changed


RELATOR_MAP = {"aut": "author", "edt": "editor", "trl": "translator", "pbl": "publisher"}


SMITH_RDA_PROFILE = (
    {"kind": "rda-classify-material", "params": {
        "mode": "classify",
        "fixed_material": "text",
        "existing_field_action": "preserve",
    }},
    {"kind": "rda-mark-rda", "params": {}},
    {"kind": "rda-remove-gmd", "params": {"value": ""}},
    {"kind": "rda-expand-abbreviations", "params": {}},
    {"kind": "rda-normalize-relators", "params": {}},
    {"kind": "rda-promote-260", "params": {}},
)


def smith_profile_operations() -> list[dict]:
    """Return a fresh, editable expansion of the visible Smith profile."""
    return [
        {"kind": item["kind"], "params": dict(item["params"])}
        for item in SMITH_RDA_PROFILE
    ]


def normalize_relators(record: Record) -> int:
    changed = 0
    for field in record.fields:
        for index, subfield in enumerate(field.subfields):
            replacement = RELATOR_MAP.get(subfield.value.casefold()) if subfield.code == "4" else None
            if replacement is not None:
                field.subfields[index] = Subfield("e", replacement)
                changed += 1
    return changed


def promote_260(record: Record) -> int:
    """Retag 260 as 264 only when no 264 exists; never merges meanings."""
    if record.get_fields("264") or not record.get_fields("260"):
        return 0
    fields = record.get_fields("260")
    record.remove_fields("260")
    for field in fields:
        field.tag = "264"
        record.add_ordered_field(field)
    return len(fields)
