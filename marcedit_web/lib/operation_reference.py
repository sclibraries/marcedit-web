"""Canonical cataloger-facing documentation for task operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from marcedit_web.lib import task_builder


GUIDE_PATH = Path(__file__).resolve().parents[2] / "docs" / "operation-reference.md"

_SPECIAL: dict[str, dict[str, Any]] = {
    "guided-find-replace": {
        "purpose": "Find text in one MARC value and replace it while preserving surrounding text by default.",
        "when_to_use": "Use this for a guided literal or raw-regex edit in a control field, one subfield, or all subfield values.",
        "behavior": "Matched-text mode changes only the matching text; whole-value mode replaces the selected value; prepend and append preserve the original value.",
        "preserves": "Text before and after a match is preserved unless whole-value replacement is selected.",
        "skip_behavior": "Values without a match are unchanged; first/all and first/last selected-value scope are explicit.",
        "error_behavior": "Invalid target, pattern, capture, or incompatible mode blocks save or execution.",
        "example": {"before": "035 $a TFeba9780203066140", "after": "035 $a (SCTFEBA)9780203066140"},
        "stored_representation": "Structured target, match mode, replacement mode, occurrence, and case parameters; raw regex is opt-in.",
        "related": ["subfield-replace", "replace-field-data-by-regex"],
    },
    "add-field": {
        "purpose": "Add one explicitly described MARC field.",
        "when_to_use": "Use when the indicators and subfields are known and no source-field template is needed.",
        "behavior": "Appends the field or follows the selected existing-field policy.",
        "preserves": "All existing fields and their source order are preserved unless replace-all is selected.",
        "skip_behavior": "A field is skipped only under the selected skip policy.",
        "error_behavior": "Invalid tags, indicators, or subfields block saving.",
        "example": {"before": "(no 877 field)", "after": "877 $m Map"},
        "stored_representation": "Tag, indicators, structured subfields, condition, and existing-field policy.",
        "related": ["build-field"],
    },
    "build-field": {
        "purpose": "Build a field from literal text and explicit control-field references.",
        "when_to_use": "Use when a new value contains data copied from fields such as 001 or 003.",
        "behavior": "Resolves each typed control-field segment and creates the requested field.",
        "preserves": "Literal text and existing record fields are preserved according to the field policy.",
        "skip_behavior": "Missing control data follows the selected skip or fail policy.",
        "error_behavior": "Malformed segments or unsupported control references block saving.",
        "example": {"before": "001 $a abc123", "after": "876 $a Babc123-SC"},
        "stored_representation": "Typed text/control-field segments, never generated executable template text.",
        "related": ["add-field"],
    },
    "rda-classify-material": {
        "purpose": "Add explicit 336, 337, and 338 fields from checked-in Leader/007 evidence or a cataloger-selected material type.",
        "when_to_use": "Use when a record needs deterministic RDA content, media, and carrier fields.",
        "behavior": "Combines content evidence from Leader/06 with explicit 007 media/carrier evidence; print text and maps use physical carriers, while 007 cr identifies online resources.",
        "preserves": "Existing 336/337/338 fields are preserved by default.",
        "skip_behavior": "Records with no unambiguous Leader/007 mapping fail with the evidence instead of guessing.",
        "error_behavior": "Unsupported material values and ambiguous evidence block the operation before adoption.",
        "example": {"before": "Leader/06=m; 007 cr", "after": "336 $a computer program $b cop\n337 $a computer $b c\n338 $a online resource $b cr"},
        "stored_representation": "Mode, fixed material override, and existing-field policy.",
        "related": ["rda-mark-rda", "rda-promote-260"],
    },
    "rda-mark-rda": {
        "purpose": "Ensure the first 040 contains the explicit RDA description term.",
        "when_to_use": "Use when local policy requires 040 $e rda.",
        "behavior": "Adds $e rda once, creating 040 only when it is absent.",
        "preserves": "All existing 040 subfields remain unchanged.",
        "skip_behavior": "An existing 040 $e rda is unchanged.",
        "error_behavior": "Malformed MARC records fail through the normal task error path.",
        "example": {"before": "040 $a DLC $b eng", "after": "040 $a DLC $b eng $e rda"},
        "stored_representation": "No opaque external setting; the operation kind is the policy.",
        "related": ["rda-classify-material"],
    },
    "rda-remove-gmd": {
        "purpose": "Remove an explicitly selected 245 $h GMD value.",
        "when_to_use": "Use when a legacy GMD must be removed during RDA cleanup.",
        "behavior": "Removes all 245 $h values when blank, or only the exact configured value.",
        "preserves": "245 title, statement, and unrelated subfields remain unchanged.",
        "skip_behavior": "Records without a matching 245 $h are unchanged.",
        "error_behavior": "Malformed input is reported; no blanket deletion of other fields occurs.",
        "example": {"before": "245 10 $a Title $h [electronic resource]", "after": "245 10 $a Title"},
        "stored_representation": "Explicit exact value parameter; blank means all 245 $h values.",
        "related": ["rda-mark-rda"],
    },
    "rda-expand-abbreviations": {
        "purpose": "Expand the reviewed abbreviation map in 300 $a.",
        "when_to_use": "Use only for the checked-in reviewed abbreviations.",
        "behavior": "Replaces exact reviewed tokens such as p., ill., and col.",
        "preserves": "Other 300 text and all unrelated fields remain unchanged.",
        "skip_behavior": "Unrecognized abbreviations are preserved.",
        "error_behavior": "Malformed records fail without free-text rewriting.",
        "example": {"before": "300 $a 1 p. : ill.", "after": "300 $a 1 pages : illustrations"},
        "stored_representation": "The operation kind selects the checked-in mapping table.",
        "related": ["rda-mark-rda"],
    },
    "rda-normalize-relators": {
        "purpose": "Add explicit $e terms for reviewed $4 relator codes while retaining the codes.",
        "when_to_use": "Use when local policy prefers spelled-out relator terms.",
        "behavior": "Maps only the reviewed aut, edt, trl, and pbl codes, adding a missing term once.",
        "preserves": "The original $4 code, existing relator terms, unknown values, and unrelated subfields remain unchanged.",
        "skip_behavior": "Fields without a reviewed code are unchanged.",
        "error_behavior": "Malformed records fail rather than applying a guessed mapping.",
        "example": {"before": "100 1  $a Doe $4 aut", "after": "100 1  $a Doe $4 aut $e author"},
        "stored_representation": "The operation kind selects the checked-in mapping table.",
        "related": ["rda-mark-rda"],
    },
    "set-008-form": {
        "purpose": "Mark form of item as online at one explicit 008 byte or at the byte selected from the Leader.",
        "when_to_use": "Use the Leader option for normal cataloger authoring; imported proven external patterns retain their original fixed position 23 or 29.",
        "behavior": "Writes o at byte 23 or 29. An explicit position is independent of Leader type, preserving the proven external instruction exactly.",
        "preserves": "Every other 008 byte and all other fields remain unchanged.",
        "skip_behavior": "Leader-based mode leaves unsupported record types unchanged; missing or short 008 fields are unchanged.",
        "error_behavior": "Any position other than Leader, 23, or 29 fails before generated task execution.",
        "example": {"before": "008 230101s2023    xx            000 0 eng d", "after": "008 230101s2023    xx o          000 0 eng d"},
        "stored_representation": "Structured position choice: Leader, 23, or 29.",
        "related": ["sort-fields"],
    },
    "rda-promote-260": {
        "purpose": "Retag 260 fields as 264 only when no 264 is already present.",
        "when_to_use": "Use when the publication statement is safe to promote without merging meanings.",
        "behavior": "Moves every 260 field to 264 with second indicator 1 (publication) when the record has no 264.",
        "preserves": "Subfields and their relative order are preserved.",
        "skip_behavior": "Records with an existing 264 or no 260 are unchanged.",
        "error_behavior": "Ambiguous publication data is left unchanged rather than merged.",
        "example": {"before": "260    $a Boston : $b Press, $c 2024", "after": "264  1 $a Boston : $b Press, $c 2024"},
        "stored_representation": "The operation kind encodes the safe promotion rule.",
        "related": ["rda-classify-material"],
    },
    "structural-find-replace": {
        "purpose": "Conditionally replace complete fields, retag fields, set indicators, or operate over a validated tag range.",
        "when_to_use": "Use structural find and replace when a whole-field or structural tag/indicator change is required.",
        "behavior": "Matched fields are changed in their existing source position. Retagging changes the tag but does not sort the record; add the explicit Sort Fields operation afterward when canonical tag order is required.",
        "preserves": "Unrelated fields and values remain unchanged; retagging preserves the field's source position until an explicit sort.",
        "skip_behavior": "Records and fields that do not match are unchanged.",
        "error_behavior": "Invalid targets, ranges, patterns, replacement pieces, or incompatible actions block saving or execution.",
        "example": {"before": "956 40 $u https://example.org", "after": "856 40 $u https://example.org (same source position until sorted)"},
        "stored_representation": "Structured target, match, action, occurrence, and replacement parameters validated by the task form.",
        "related": ["sort-fields"],
    },
}

# Keep examples concrete even for older palette operations.  These are
# sanitized MARC snippets, not fixtures copied from institutional records.
_EXAMPLES: dict[str, tuple[str, str]] = {
    "delete-tag": ("029 $a obsolete", "(029 field removed)"),
    "delete-by-subfield": ("650 $a History $2 local", "(650 removed when a subfield contains the match)"),
    "delete-856-url-contains": ("856 $u https://old.example/item", "(856 removed when URL contains the configured text)"),
    "delete-856-url-regex": ("856 $u https://example.org/item.pdf", "(856 removed when URL matches the regex)"),
    "subfield-replace": ("035 $a TFeba9780203066140", "035 $a (SCTFEBA)9780203066140"),
    "empty-find-subfield-policy": ("856 $u https://example.org", "856 $u https://example.org $y Smith link"),
    "copy-field": ("245 $a Title", "245 $a Title\n246 $a Title"),
    "move-field": ("490 $a Series", "830 $a Series"),
    "add-subfield": ("856 $u https://example.org", "856 $u https://example.org $y Smith: Link"),
    "delete-subfield": ("650 $a History $9 local", "650 $a History"),
    "delete-subfield-if-value": ("856 $u https://example.org $y obsolete", "856 $u https://example.org"),
    "copy-subfield": ("035 $a abc", "035 $a abc $z abc"),
    "edit-indicators": ("245 10 $a Title", "245 00 $a Title"),
    "replace-field-data-by-regex": ("008 230101s2023    xx            000 0 eng d", "008 230101s2023    xx            000 0 eng d (matched data changed)"),
    "replace-field-subfield-and-indicators": ("035 00 $a TFeba9780203066140", "035 09 $a (SCTFEBA)"),
    "sort-fields": ("040 $a ABC\n020 $a 123", "020 $a 123\n040 $a ABC"),
    "set-008-form": ("008 230101s2023    xx            000 0 eng d", "008 230101s2023    xx o          000 0 eng d"),
    "rda-classify-material": ("Leader/06=m; 007 cr", "336 $a computer program $b cop\n337 $a computer $b c\n338 $a online resource $b cr"),
    "rda-mark-rda": ("040 $a DLC $b eng", "040 $a DLC $b eng $e rda"),
    "rda-remove-gmd": ("245 10 $a Title $h [electronic resource]", "245 10 $a Title"),
    "rda-expand-abbreviations": ("300 $a 1 p. : ill.", "300 $a 1 pages : illustrations"),
    "rda-normalize-relators": ("100 1  $a Doe $4 aut", "100 1  $a Doe $4 aut $e author"),
    "rda-promote-260": ("260    $a Boston : $b Press, $c 2024", "264  1 $a Boston : $b Press, $c 2024"),
    "structural-find-replace": ("245 10 $a Old title", "245 10 $a New title (or another explicitly selected structural change)"),
    "custom": ("(technical Python operation)", "(technical Python operation remains unchanged)"),
}


def _generic_entry(palette: dict[str, Any]) -> dict[str, Any]:
    kind = str(palette["kind"])
    label = str(palette["label"])
    inputs = [str(param["name"]) for param in palette["params"]]
    return {
        "purpose": str(palette["summary"]),
        "when_to_use": f"Use {label.lower()} when that specific MARC change is required.",
        "inputs": inputs,
        "behavior": str(palette["summary"]),
        "preserves": "Unrelated fields and values remain unchanged.",
        "skip_behavior": "Records that do not match the operation are unchanged.",
        "error_behavior": "Invalid inputs are reported before the task is saved or run.",
        "example": {
            "before": _EXAMPLES.get(kind, ("MARC field before operation", "MARC field after operation"))[0],
            "after": _EXAMPLES.get(kind, ("MARC field before operation", "MARC field after operation"))[1],
        },
        "stored_representation": f"Structured `{kind}` parameters validated by the task form.",
        "related": [],
    }


REFERENCE_REGISTRY: dict[str, dict[str, Any]] = {}
for _palette_entry in task_builder.OPERATIONS_PALETTE:
    _kind = str(_palette_entry["kind"])
    _entry = _generic_entry(_palette_entry)
    _entry.update(_SPECIAL.get(_kind, {}))
    _entry["label"] = _palette_entry["label"]
    _entry["summary"] = _palette_entry["summary"]
    _entry["inputs"] = [param["name"] for param in _palette_entry["params"]]
    REFERENCE_REGISTRY[_kind] = _entry


_QUICK_OVERVIEW = (
    "Common Quick field changes are one-operation edits: choose one change, read its "
    "summary, Preview, then Apply the same current preview. Existing fields are "
    "filtered before the First, Last, Numbered, or Every occurrence is chosen. "
    "Records missing a requested occurrence are skipped and grouped by reason. "
    "Guided matching is the normal path; an optional Advanced regular expression "
    "is available when needed. Preview and Apply are recoverable, and a changed "
    "selector requires a new Preview."
)

# Quick changes intentionally have their own registry.  Several labels share a
# kind with saved-task palette operations, but their selector and occurrence
# semantics are different and must not change the task-palette contract above.
QUICK_CHANGE_REFERENCE: dict[str, dict[str, Any]] = {
    "add-field": {
        "label": "Add field",
        "purpose": "Add one explicitly described control or data field.",
        "when_to_use": "Use when a field should be added once without saving a task.",
        "inputs": ["destination tag", "indicators", "subfields or control value", "record scope"],
        "behavior": "Adds the field to every record, or only when its tag or complete identity is absent.",
        "preserves": "Existing fields, their values, and their source order remain unchanged.",
        "skip_behavior": "A record is unchanged when its selected add-field scope says the field is already present.",
        "error_behavior": "Invalid tags, indicators, control values, or subfield rows block Preview.",
        "example": {"before": "(no 877 field)", "after": "877  $m Map"},
        "stored_representation": "A plain-language field request; it is not a saved task.",
        "related": [],
    },
    "add-subfield": {
        "label": "Add subfield",
        "purpose": "Append or prepend one code and value to selected variable fields.",
        "when_to_use": "Use when existing fields need one explicit subfield added.",
        "inputs": ["field filter", "occurrence", "subfield code", "subfield value", "position", "repeat policy"],
        "behavior": "Adds the pair to the fields that pass the filter and then the chosen occurrence.",
        "preserves": "Field tags, indicators, existing ordered subfields, and unrelated fields remain unchanged.",
        "skip_behavior": "Records with no matching occurrence are skipped and listed by the selector reason.",
        "error_behavior": "Control fields, invalid codes, and invalid matcher values block Preview.",
        "example": {"before": "856 40 $u https://vendor.example/item", "after": "856 40 $u https://vendor.example/item $y Vendor link"},
        "stored_representation": "A one-operation selection and subfield change, not reusable task code.",
        "related": ["delete-subfield"],
    },
    "copy-field": {
        "label": "Copy field",
        "purpose": "Deep-copy selected complete fields to one destination tag.",
        "when_to_use": "Use when selected fields should also appear under another tag.",
        "inputs": ["field filter", "occurrence", "destination tag", "destination policy"],
        "behavior": "Copies only fields resolved after filtering and occurrence selection; choose Append, Skip identical, or Replace all destination fields.",
        "preserves": "Source fields and complete indicators and subfield order are preserved.",
        "skip_behavior": "Records without a selected source field are skipped without changing destination fields.",
        "error_behavior": "Incompatible control/data tags or invalid destination policies block Preview.",
        "example": {"before": "245 10 $a Title", "after": "245 10 $a Title\n246 30 $a Title"},
        "stored_representation": "A bounded field selection and explicit destination policy.",
        "related": [],
    },
    "delete-field": {
        "label": "Delete field",
        "purpose": "Remove selected complete fields.",
        "when_to_use": "Use when only a chosen occurrence or filtered set should be removed.",
        "inputs": ["field filter", "occurrence"],
        "behavior": "Removes the fields that pass the filter and then the selected First, Last, Numbered, or Every occurrence.",
        "preserves": "All non-selected fields and the relative order of remaining fields remain unchanged.",
        "skip_behavior": "Records with no selected occurrence are skipped and grouped by reason.",
        "error_behavior": "Invalid tags, filters, occurrence choices, or unsafe matchers block Preview.",
        "example": {"before": "856 40 $u https://old.example/item", "after": "(selected 856 field removed)"},
        "stored_representation": "A one-time filtered field deletion; tag ranges and wildcards are not inferred.",
        "related": [],
    },
    "delete-subfield": {
        "label": "Delete subfield",
        "purpose": "Remove one code from selected variable fields, optionally matching its value.",
        "when_to_use": "Use when a subfield must be removed from only the intended fields.",
        "inputs": ["field filter", "occurrence", "subfield code", "value match", "subfield occurrence", "remove empty field"],
        "behavior": "Removes the first or every matching subfield after field filtering and occurrence selection.",
        "preserves": "Other subfields, field identity, and unrelated fields remain unchanged unless empty-field removal is selected.",
        "skip_behavior": "Missing fields or values are skipped and reported by reason rather than guessed.",
        "error_behavior": "Control fields, invalid codes, and invalid guided or regular-expression matchers block Preview.",
        "example": {"before": "856 40 $u https://vendor.example/item $y obsolete", "after": "856 40 $u https://vendor.example/item"},
        "stored_representation": "A bounded one-time subfield selection and removal choice.",
        "related": ["add-subfield"],
    },
    "move-field": {
        "label": "Move or retag field",
        "purpose": "Change selected fields to a destination tag while retaining their complete contents.",
        "when_to_use": "Use when a field needs a new tag but should stay in its current record position.",
        "inputs": ["field filter", "occurrence", "destination tag"],
        "behavior": "Retags only the selected fields; it does not sort or otherwise reorder the record.",
        "preserves": "Indicators, ordered subfields, values, and source positions are preserved. Reorder fields is a separate explicit Quick action.",
        "skip_behavior": "Records without a selected occurrence are skipped and grouped by selector reason.",
        "error_behavior": "Incompatible control/data tags and invalid destination tags block Preview.",
        "example": {"before": "490  $a Series", "after": "830  $a Series (same source position)"},
        "stored_representation": "A one-time retag selection; sorting remains an explicit separate operation.",
        "related": ["sort-fields"],
    },
    "remove-duplicate-fields": {
        "label": "Remove exact duplicate fields",
        "purpose": "Remove repeated fields only when their complete MARC identity is exactly equal.",
        "when_to_use": "Use when exact duplicates should be reduced while near-duplicates remain for review.",
        "inputs": ["field filter", "keep first or last"],
        "behavior": "Groups filtered fields by tag, indicators or control value, and ordered subfield code/value pairs, then keeps the chosen copy.",
        "preserves": "Near-duplicates, unique fields, and the relative order of surviving fields remain unchanged.",
        "skip_behavior": "Records with no duplicate group are unchanged; no similar field is treated as a duplicate.",
        "error_behavior": "Invalid duplicate filters or keep choices block Preview.",
        "example": {"before": "035  $a (OCoLC)123\n035  $a (OCoLC)123", "after": "035  $a (OCoLC)123"},
        "stored_representation": "An exact-identity cleanup request, not a fuzzy duplicate matcher.",
        "related": [],
    },
    "set-indicators": {
        "label": "Set indicators",
        "purpose": "Set indicator 1, indicator 2, or both on selected data fields.",
        "when_to_use": "Use when selected fields need explicit indicator values without changing their data.",
        "inputs": ["field filter", "occurrence", "indicator 1", "indicator 2"],
        "behavior": "Writes only the chosen indicator values on fields resolved after filtering and occurrence selection.",
        "preserves": "Tags, ordered subfields, values, and unchanged indicators remain intact.",
        "skip_behavior": "Records with no selected occurrence or no effective change are unchanged and reported accordingly.",
        "error_behavior": "Control fields, missing indicator choices, or invalid filters block Preview.",
        "example": {"before": "245 10 $a Title", "after": "245 00 $a Title"},
        "stored_representation": "An explicit one-time indicator edit with Leave unchanged and MARC blank choices.",
        "related": [],
    },
    "swap-field-occurrences": {
        "label": "Swap field occurrences",
        "purpose": "Exchange two distinct complete fields with the same tag.",
        "when_to_use": "Use when two same-tag fields need their source-order positions exchanged.",
        "inputs": ["first field filter and occurrence", "second field filter and occurrence"],
        "behavior": "Swaps the complete selected field objects, preserving each field's tag, indicators, control value, and ordered subfields.",
        "preserves": "Field contents are untouched; only the two selected source positions change.",
        "skip_behavior": "Missing sides and selectors resolving to the same field are skipped and grouped by reason.",
        "error_behavior": "Selectors must be distinct and use the same exact tag; Every is not available for Swap.",
        "example": {"before": "070  4 $a QA76.73.P98\n070  4 $a QA76.73.P99", "after": "070  4 $a QA76.73.P99\n070  4 $a QA76.73.P98"},
        "stored_representation": "Two explicit one-time selectors; no field contents are reconstructed.",
        "related": [],
    },
}


def _search_registry_entries(query: str = "") -> list[dict[str, Any]]:
    needle = query.strip().casefold()
    entries = []
    for kind, entry in REFERENCE_REGISTRY.items():
        haystack = " ".join(
            [
                kind,
                str(entry.get("label", "")),
                str(entry.get("summary", "")),
                str(entry.get("purpose", "")),
                str(entry.get("when_to_use", "")),
                " ".join(str(item) for item in entry.get("inputs", [])),
                " ".join(str(item) for item in entry.get("related", [])),
            ]
        ).casefold()
        if not needle or needle in haystack:
            entries.append({"kind": kind, **entry})
    return sorted(entries, key=lambda entry: str(entry["label"]).casefold())


def search_quick_entries(query: str = "") -> list[dict[str, Any]]:
    """Return cataloger-facing Common field changes reference entries."""

    needle = query.strip().casefold()
    entries = []
    for kind, entry in QUICK_CHANGE_REFERENCE.items():
        haystack = " ".join(
            [
                kind,
                str(entry.get("label", "")),
                str(entry.get("purpose", "")),
                str(entry.get("when_to_use", "")),
                str(entry.get("behavior", "")),
                str(entry.get("preserves", "")),
                str(entry.get("skip_behavior", "")),
                str(entry.get("error_behavior", "")),
                str(entry.get("stored_representation", "")),
                " ".join(str(item) for item in entry.get("inputs", [])),
                " ".join(str(item) for item in entry.get("related", [])),
                _QUICK_OVERVIEW,
            ]
        ).casefold()
        if not needle or needle in haystack:
            entries.append({"kind": kind, "source": "quick", **entry})
    return sorted(entries, key=lambda entry: str(entry["label"]).casefold())


def search_entries(query: str = "") -> list[dict[str, Any]]:
    """Search saved-task and Common field changes reference entries."""

    return sorted(
        _search_registry_entries(query) + search_quick_entries(query),
        key=lambda entry: (str(entry["label"]).casefold(), entry.get("source", "task")),
    )


def render_markdown() -> str:
    lines = [
        "# Task operation reference",
        "",
        "This guide is generated from the checked-in deterministic operation registry.",
        "",
    ]
    for entry in _search_registry_entries():
        lines.extend([
            f"## {entry['label']}",
            "",
            f"**Operation kind:** `{entry['kind']}`",
            "",
            f"**Purpose:** {entry['purpose']}",
            "",
            f"**When to use:** {entry['when_to_use']}",
            "",
            f"**Inputs:** {', '.join(f'`{item}`' for item in entry['inputs']) or 'none'}",
            "",
            f"**Behavior:** {entry['behavior']}",
            "",
            f"**Preserves:** {entry['preserves']}",
            "",
            f"**Skip behavior:** {entry['skip_behavior']}",
            "",
            f"**Error behavior:** {entry['error_behavior']}",
            "",
            f"**Before:** `{entry['example']['before']}`",
            "",
            f"**After:** `{entry['example']['after']}`",
            "",
            f"**Stored representation:** {entry['stored_representation']}",
            "",
            f"**Related:** {', '.join(f'`{item}`' for item in entry['related']) or 'none'}",
            "",
        ])
    lines.extend([
        "## Common field changes",
        "",
        _QUICK_OVERVIEW,
        "",
        "These nine labels are alphabetical. Choose exactly one for each Preview and Apply cycle.",
        "",
    ])
    for entry in search_quick_entries():
        lines.extend([
            f"### {entry['label']}",
            "",
            f"**Purpose:** {entry['purpose']}",
            "",
            f"**When to use:** {entry['when_to_use']}",
            "",
            f"**Inputs:** {', '.join(entry['inputs']) or 'none'}",
            "",
            f"**Behavior:** {entry['behavior']}",
            "",
            f"**Preserves:** {entry['preserves']}",
            "",
            f"**Skip behavior:** {entry['skip_behavior']}",
            "",
            f"**Error behavior:** {entry['error_behavior']}",
            "",
            f"**Before:** `{entry['example']['before']}`",
            "",
            f"**After:** `{entry['example']['after']}`",
            "",
            f"**Related:** {', '.join(f'`{item}`' for item in entry['related']) or 'none'}",
            "",
        ])
    lines.extend([
        "### Worked examples",
        "",
        "To swap two distinguishable 070 fields, choose **Swap field occurrences**, enter tag `070`, and select the first and second occurrences. The complete fields exchange positions; each indicator, value, and ordered subfield stays with its field.",
        "",
        "To select one of several 856 fields, enter tag `856`, choose subfield `$u`, use the guided **Contains** match for the vendor text, then choose **Numbered** for the requested matching occurrence. Filtering happens before numbering, so a nonmatching vendor link is not counted.",
        "",
        "**Move or retag field** keeps the source position. Use the separate explicit **Reorder fields** Quick action when tag order should be normalized.",
        "",
        "Exact duplicate removal compares complete field identity (tag, indicators or control value, and ordered subfields); near-duplicates are retained.",
        "",
        "Preview and Apply are recoverable: reset clears preview evidence, stale source or changed selectors disable Apply, and a successful Apply creates the existing history or recoverable file-version evidence.",
        "",
    ])
    return "\n".join(lines).rstrip("\n") + "\n"
