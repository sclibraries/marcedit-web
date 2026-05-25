"""Form-based task authoring — the cataloger-friendly path to a new task.

The Tasks page editor has two modes. **Code view** is the raw textarea
(good for power users). **Form view** is an ordered list of typed
"operations" — Delete tag, Add field, Sort, etc. — each with a small form
for its parameters. This module is the model behind Form view.

Each operation has:
  * a `kind` (e.g. `"delete-tag"`) — keys into `OPERATIONS_PALETTE`;
  * a `params` dict with operation-specific values.

When the form is saved, `render_ops_to_python` emits the body of the task
function. Each operation is preceded by a `# OP: <kind> <json-params>`
marker that `parse_ops_from_source` recognizes when a task file is opened
again, so the round-trip preserves the structured representation.

A task body without any `# OP:` markers (e.g. one hand-written in Code
view) is opaque to the parser and the editor falls back to Code view.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from marcedit_web.lib.codegen_safety import lit

logger = logging.getLogger("marcedit_web.task_builder")


# ---------------------------------------------------------------------------
# Operation data
# ---------------------------------------------------------------------------


@dataclass
class Operation:
    """One step in a form-built task."""

    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "params": self.params}

    @classmethod
    def from_dict(cls, data: dict) -> "Operation":
        return cls(kind=data["kind"], params=dict(data.get("params") or {}))


# Leader-condition presets the cataloger picks from a dropdown. Each value is
# a key into `_LEADER_CONDITIONS`; the empty string is the "always apply" case.
LEADER_CONDITIONS: dict[str, str] = {
    "always": "",
    "books": "leader_type(record) in 'amt' and leader_biblevel(record) == 'm'",
    "serials": "leader_biblevel(record) == 's'",
    "databases": "leader_biblevel(record) == 'i'",
    "maps": "leader_type(record) in 'ef'",
    "videos": "leader_type(record) == 'g'",
    "audios": "leader_type(record) in 'ij'",
    "scores": "leader_type(record) in 'cd'",
}

LEADER_CONDITION_LABELS: dict[str, str] = {
    "always": "Always — apply to every record",
    "books": "Books (LDR 06 ∈ amt, LDR 07 = m)",
    "serials": "Serials (LDR 07 = s)",
    "databases": "Databases / integrating resources (LDR 07 = i)",
    "maps": "Maps & cartographic (LDR 06 ∈ ef)",
    "videos": "Streaming video (LDR 06 = g)",
    "audios": "Streaming audio (LDR 06 ∈ ij)",
    "scores": "Scores / notated music (LDR 06 ∈ cd)",
}


# ---------------------------------------------------------------------------
# Palette — operation types + their parameter schemas
# ---------------------------------------------------------------------------


OPERATIONS_PALETTE: list[dict] = [
    {
        "kind": "delete-tag",
        "label": "Delete tag",
        "summary": "Remove every field with this tag.",
        "params": [
            {
                "name": "tag", "label": "Tag", "type": "text",
                "placeholder": "e.g. 029, 891, or 9XX (use X as a digit wildcard)",
                "required": True,
            },
        ],
    },
    {
        "kind": "delete-by-subfield",
        "label": "Delete fields matching subfield value",
        "summary": "Remove fields whose subfield value contains the given text.",
        "params": [
            {"name": "tag", "label": "Tag", "type": "text", "required": True},
            {
                "name": "match", "label": "Match (any subfield contains)",
                "type": "text", "required": True,
                "placeholder": "e.g. Electronic books",
            },
        ],
    },
    {
        "kind": "delete-856-url-contains",
        "label": "Delete 856 by URL text",
        "summary": "Remove 856 fields whose URL contains the given text.",
        "params": [
            {
                "name": "match", "label": "URL contains",
                "type": "text", "required": True,
                "placeholder": "e.g. oclc.org/content/dam/oclc/forms/terms",
            },
        ],
    },
    {
        "kind": "delete-856-url-regex",
        "label": "Delete 856 by URL regex",
        "summary": "Remove 856 fields whose URL matches the given regex (re.search; case-insensitive by default).",
        "params": [
            {
                "name": "pattern", "label": "URL regex",
                "type": "text", "required": True,
                "placeholder": r"e.g. \.pdf(\?|$)  or  ^https?://(www\.)?oclc\.org/",
            },
            {
                "name": "ignore_case", "label": "Case-insensitive",
                "type": "bool", "default": True,
            },
        ],
    },
    {
        "kind": "add-field",
        "label": "Add field",
        "summary": "Insert a new field with given indicators and subfields.",
        "params": [
            {"name": "tag", "label": "Tag", "type": "text", "required": True},
            {"name": "ind1", "label": "Indicator 1", "type": "indicator", "default": " "},
            {"name": "ind2", "label": "Indicator 2", "type": "indicator", "default": " "},
            {
                "name": "subfields", "label": "Subfields", "type": "subfields",
                "required": True,
            },
            {
                "name": "condition", "label": "Apply when",
                "type": "select",
                "options": [{"value": k, "label": v} for k, v in LEADER_CONDITION_LABELS.items()],
                "default": "always",
            },
            {
                "name": "if_absent", "label": "Skip if a field with this tag already exists",
                "type": "bool", "default": False,
            },
        ],
    },
    {
        "kind": "build-field",
        "label": "Build field from template",
        "summary": (
            "Like Add field, but subfield values may contain {NNN} tokens that "
            "are substituted with the matching control field at runtime (e.g. "
            "({003}){001} for a Smith-style 035 9). The whole field is skipped "
            "if any referenced control field is missing."
        ),
        "params": [
            {"name": "tag", "label": "Tag", "type": "text", "required": True},
            {"name": "ind1", "label": "Indicator 1", "type": "indicator", "default": " "},
            {"name": "ind2", "label": "Indicator 2", "type": "indicator", "default": " "},
            {
                "name": "subfields", "label": "Subfields (values may use {NNN} tokens)",
                "type": "subfields", "required": True,
            },
            {
                "name": "condition", "label": "Apply when",
                "type": "select",
                "options": [{"value": k, "label": v} for k, v in LEADER_CONDITION_LABELS.items()],
                "default": "always",
            },
            {
                "name": "if_absent", "label": "Skip if a field with this tag already exists",
                "type": "bool", "default": False,
            },
        ],
    },
    {
        "kind": "subfield-replace",
        "label": "Find & replace in subfield",
        "summary": (
            "Replace text inside a specific subfield code on a tag. "
            "Toggle **Treat Find as regex** for pattern-based finds; "
            "leave it off for literal text."
        ),
        "params": [
            {"name": "tag", "label": "Tag", "type": "text", "required": True},
            {"name": "code", "label": "Subfield code", "type": "subfield_code", "required": True},
            {"name": "find", "label": "Find", "type": "text", "required": True},
            {"name": "replace", "label": "Replace with", "type": "text"},
            {"name": "regex", "label": "Treat Find as regex", "type": "bool", "default": False},
            {"name": "ignore_case", "label": "Case-insensitive", "type": "bool", "default": False},
        ],
    },
    # --- TASK-030 new ops ---------------------------------------------------
    {
        "kind": "copy-field",
        "label": "Copy field",
        "summary": (
            "Duplicate every field with the source tag as a new field "
            "with the destination tag. The original stays in place."
        ),
        "params": [
            {"name": "src_tag", "label": "Source tag", "type": "text", "required": True},
            {"name": "dst_tag", "label": "Destination tag", "type": "text", "required": True},
        ],
    },
    {
        "kind": "move-field",
        "label": "Move (re-tag) field",
        "summary": (
            "Re-tag every field with the source tag as the destination "
            "tag. Same as Copy field followed by Delete tag, but in one "
            "atomic op."
        ),
        "params": [
            {"name": "src_tag", "label": "Source tag", "type": "text", "required": True},
            {"name": "dst_tag", "label": "Destination tag", "type": "text", "required": True},
        ],
    },
    {
        "kind": "add-subfield",
        "label": "Add subfield to existing fields",
        "summary": (
            "Append (or prepend) a subfield to every variable field "
            "with the given tag. Control fields (00X) are skipped."
        ),
        "params": [
            {"name": "tag", "label": "Tag", "type": "text", "required": True},
            {"name": "code", "label": "Subfield code", "type": "subfield_code", "required": True},
            {"name": "value", "label": "Value", "type": "text", "required": True},
            {
                "name": "position", "label": "Position",
                "type": "select",
                "options": [
                    {"value": "end", "label": "Append (end of field)"},
                    {"value": "start", "label": "Prepend (start of field)"},
                ],
                "default": "end",
            },
        ],
    },
    {
        "kind": "delete-subfield",
        "label": "Delete subfields by code",
        "summary": (
            "Strip the listed subfield codes from every field with the "
            "given tag. Multiple codes are comma- or space-separated."
        ),
        "params": [
            {"name": "tag", "label": "Tag", "type": "text", "required": True},
            {
                "name": "codes",
                "label": "Subfield codes (comma- or space-separated)",
                "type": "text", "required": True,
                "placeholder": "e.g. 5, 9",
            },
        ],
    },
    {
        "kind": "copy-subfield",
        "label": "Copy subfield within field",
        "summary": (
            "Within each matching field, copy each existing source "
            "subfield's value into a new subfield with the destination "
            "code. Useful for invalidating in place ($a → $z)."
        ),
        "params": [
            {"name": "tag", "label": "Tag", "type": "text", "required": True},
            {"name": "src_code", "label": "Source subfield code", "type": "subfield_code", "required": True},
            {"name": "dst_code", "label": "Destination subfield code", "type": "subfield_code", "required": True},
        ],
    },
    {
        "kind": "edit-indicators",
        "label": "Set indicators",
        "summary": (
            "Override one or both indicators on every field with the "
            "given tag. Leave an indicator blank to keep the existing "
            "value (use a space to set blank)."
        ),
        "params": [
            {"name": "tag", "label": "Tag", "type": "text", "required": True},
            {
                "name": "ind1", "label": "Indicator 1 (empty = leave alone)",
                "type": "text",
                "placeholder": "single char, or space for blank",
            },
            {
                "name": "ind2", "label": "Indicator 2 (empty = leave alone)",
                "type": "text",
                "placeholder": "single char, or space for blank",
            },
        ],
    },
    {
        "kind": "replace-field-data-by-regex",
        "label": "Replace field data by regex",
        "summary": (
            "Apply a regex find/replace across every field with the "
            "given tag. Control fields edit `.data`; variable fields "
            "edit each subfield value."
        ),
        "params": [
            {"name": "tag", "label": "Tag", "type": "text", "required": True},
            {
                "name": "pattern", "label": "Regex pattern",
                "type": "text", "required": True,
                "placeholder": r"e.g. \s+$  to strip trailing whitespace",
            },
            {"name": "replacement", "label": "Replacement", "type": "text"},
            {
                "name": "ignore_case", "label": "Case-insensitive",
                "type": "bool", "default": False,
            },
        ],
    },
    {
        "kind": "sort-fields",
        "label": "Sort fields by tag",
        "summary": "Reorder all variable fields by tag (used as a final step).",
        "params": [],
    },
    {
        "kind": "set-008-form",
        "label": "Set 008 form-of-item to 'o' (online)",
        "summary": "Mark the record as an online resource by writing 'o' into 008 (byte 23 or 29, leader-dependent).",
        "params": [],
    },
    {
        "kind": "custom",
        "label": "Custom Python (advanced)",
        "summary": "Drop in raw Python for anything the palette doesn't cover.",
        "params": [
            {
                "name": "code", "label": "Python code", "type": "code",
                "placeholder": "# 'record' is a pymarc.Record. Mutate in place.",
            },
        ],
    },
]


def list_operation_types() -> list[dict]:
    """Return the palette as a JSON-serializable list (for the GUI bridge)."""
    # Return deepcopies so callers can't mutate our module-level constant.
    return [
        {**op, "params": [dict(p) for p in op["params"]]}
        for op in OPERATIONS_PALETTE
    ]


# ---------------------------------------------------------------------------
# Render: ops -> Python
# ---------------------------------------------------------------------------


_OP_MARKER_PREFIX = "# OP:"


def _format_subfield_args(subfields: list) -> str:
    """`[["a", "Hello"], ["5", "MNS"]]` -> `("a", "Hello"), ("5", "MNS")`"""
    if not subfields:
        return ""
    return ", ".join(
        f"({lit(sf[0])}, {lit(sf[1])})" for sf in subfields
    )


def _extract_template_tokens(subfields: list) -> list[str]:
    """Return the unique control-field tags referenced across all subfield
    values, in first-seen order.

    `[["a", "({003}){001}"], ["5", "MNS"]]` -> `["003", "001"]`.
    Raises `ValueError` if a value contains a `{...}` placeholder that
    isn't a 3-digit tag — that almost always means the cataloger typed
    `{1}` or `{name}` and would otherwise hit a confusing format() error
    at runtime.
    """
    seen: list[str] = []
    for _, value in subfields:
        text = str(value)
        for match in re.finditer(r"\{([^{}]*)\}", text):
            inner = match.group(1)
            if not re.fullmatch(r"\d{3}", inner):
                raise ValueError(
                    f"build-field template placeholder {{{inner}}} is not a "
                    f"3-digit control-field tag (e.g. {{001}}, {{003}})"
                )
            if inner not in seen:
                seen.append(inner)
    return seen


def _render_one(op: Operation) -> tuple[list[str], set[str], bool]:
    """Render a single operation.

    Returns `(code_lines, imports_needed, needs_subfield_import)`.
    """
    p = op.params
    if op.kind == "delete-tag":
        tag = str(p.get("tag", "")).strip()
        return ([f"delete_tags(record, {lit(tag)})"], {"delete_tags"}, False)

    if op.kind == "delete-by-subfield":
        tag = str(p.get("tag", "")).strip()
        match = str(p.get("match", ""))
        return (
            [f"delete_fields_matching_subfield(record, {lit(tag)}, None, {lit(match)})"],
            {"delete_fields_matching_subfield"},
            False,
        )

    if op.kind == "delete-856-url-contains":
        match = str(p.get("match", ""))
        return (
            [f"delete_856_fields_matching_url(record, {lit(match)})"],
            {"delete_856_fields_matching_url"},
            False,
        )

    if op.kind == "delete-856-url-regex":
        pattern = str(p.get("pattern", ""))
        # Default to case-insensitive — matches the palette default and the
        # cataloger expectation that `oclc.org` matches `OCLC.ORG`.
        ignore_case = bool(p.get("ignore_case", True))
        return (
            [
                f"delete_856_fields_matching_url_regex(record, {lit(pattern)}, "
                f"ignore_case={ignore_case})"
            ],
            {"delete_856_fields_matching_url_regex"},
            False,
        )

    if op.kind == "add-field":
        tag = str(p.get("tag", "")).strip()
        ind1 = (p.get("ind1") or " ")[:1] or " "
        ind2 = (p.get("ind2") or " ")[:1] or " "
        subfields = list(p.get("subfields") or [])
        sf_args = _format_subfield_args(subfields)
        prefix = "add_field_if_absent" if p.get("if_absent") else "record.add_ordered_field"
        make_call = f"make_field({lit(tag)}, {lit(ind1)}, {lit(ind2)}, {sf_args})"
        if p.get("if_absent"):
            stmt = f"add_field_if_absent(record, {make_call})"
            imports = {"add_field_if_absent", "make_field"}
        else:
            stmt = f"record.add_ordered_field({make_call})"
            imports = {"make_field"}
        condition_key = p.get("condition") or "always"
        condition_expr = LEADER_CONDITIONS.get(condition_key, "")
        if condition_expr:
            imports |= {"leader_type", "leader_biblevel"}
            return ([f"if {condition_expr}:", f"    {stmt}"], imports, False)
        return ([stmt], imports, False)

    if op.kind == "build-field":
        tag = str(p.get("tag", "")).strip()
        ind1 = (p.get("ind1") or " ")[:1] or " "
        ind2 = (p.get("ind2") or " ")[:1] or " "
        subfields = list(p.get("subfields") or [])
        # Validate placeholders up front so malformed templates fail at
        # render time (when the cataloger is editing) instead of at run time.
        tokens = _extract_template_tokens(subfields)
        imports: set[str] = {"make_field"}
        condition_key = p.get("condition") or "always"
        condition_expr = LEADER_CONDITIONS.get(condition_key, "")

        # No template tokens? Fall back to the same shape as add-field —
        # build-field stays usable as a strict superset.
        if not tokens:
            sf_args = _format_subfield_args(subfields)
            make_call = (
                f"make_field({lit(tag)}, {lit(ind1)}, {lit(ind2)}, {sf_args})"
            )
            if p.get("if_absent"):
                stmt = f"add_field_if_absent(record, {make_call})"
                imports |= {"add_field_if_absent"}
            else:
                stmt = f"record.add_ordered_field({make_call})"
            if condition_expr:
                imports |= {"leader_type", "leader_biblevel"}
                return ([f"if {condition_expr}:", f"    {stmt}"], imports, False)
            return ([stmt], imports, False)

        # Template path: look up each referenced control field, guard on
        # non-None (skip the whole add if any is missing), then substitute
        # via chained `.replace()` calls. We can't use str.format() here:
        # numeric placeholders like `{001}` are treated as positional
        # indices by Python's format machinery (IndexError on call),
        # even when passed via **kwargs. Tags are 3-digit so no token
        # is a prefix of another, making the replace order irrelevant.
        imports |= {"control_value"}
        lookup_lines = [
            f"_t_{tok} = control_value(record, {lit(tok)})" for tok in tokens
        ]
        guard = " and ".join(f"_t_{tok} is not None" for tok in tokens)
        sf_items: list[str] = []
        for code, value in subfields:
            value_str = str(value)
            if re.search(r"\{\d{3}\}", value_str):
                replace_chain = "".join(
                    f".replace({lit('{' + tok + '}')}, _t_{tok})"
                    for tok in tokens
                    if f"{{{tok}}}" in value_str
                )
                sf_items.append(f"({lit(code)}, {lit(value)}{replace_chain})")
            else:
                sf_items.append(f"({lit(code)}, {lit(value)})")
        sf_args = ", ".join(sf_items)
        make_call = f"make_field({lit(tag)}, {lit(ind1)}, {lit(ind2)}, {sf_args})"
        if p.get("if_absent"):
            add_stmt = f"add_field_if_absent(record, {make_call})"
            imports |= {"add_field_if_absent"}
        else:
            add_stmt = f"record.add_ordered_field({make_call})"

        # Indent the guarded body. If a leader condition is also present,
        # wrap the whole block in the outer condition.
        body_lines = lookup_lines + [f"if {guard}:", f"    {add_stmt}"]
        if condition_expr:
            imports |= {"leader_type", "leader_biblevel"}
            return (
                [f"if {condition_expr}:"]
                + [f"    {line}" for line in body_lines],
                imports,
                False,
            )
        return (body_lines, imports, False)

    if op.kind == "subfield-replace":
        tag = str(p.get("tag", "")).strip()
        code = str(p.get("code", "")).strip()
        find = str(p.get("find", ""))
        replace = str(p.get("replace", ""))
        use_regex = bool(p.get("regex", False))
        ignore_case = bool(p.get("ignore_case", False))
        if use_regex:
            # Regex path emits one ``re.sub`` per subfield value.
            # ``re`` is imported by the rendered task file (we mark
            # the special ``_re_import`` marker that the file
            # renderer translates into ``import re``).
            flags_expr = "re.IGNORECASE" if ignore_case else "0"
            return (
                [
                    f"_pat = re.compile({lit(find)}, {flags_expr})",
                    f"for f in record.get_fields({lit(tag)}):",
                    "    f.subfields = [",
                    f"        Subfield(sf.code, _pat.sub({lit(replace)}, sf.value))",
                    f"        if sf.code == {lit(code)} else sf",
                    "        for sf in f.subfields",
                    "    ]",
                ],
                {"_re_import"},
                True,  # needs Subfield import from pymarc
            )
        # Literal path — preserves the pre-TASK-030 behavior bit-for-bit
        # so saved tasks with regex=False keep emitting the same code.
        replace_call = f"sf.value.replace({lit(find)}, {lit(replace)})"
        if ignore_case:
            # Literal + case-insensitive emulates "find any
            # case-folded occurrence" by lower-casing for the match
            # only. Use ``re.sub(re.escape(find), ..., re.IGNORECASE)``
            # so we don't roll our own walker.
            replace_call = (
                f"re.sub(re.escape({lit(find)}), {lit(replace)}, sf.value, "
                f"flags=re.IGNORECASE)"
            )
            return (
                [
                    f"for f in record.get_fields({lit(tag)}):",
                    "    f.subfields = [",
                    f"        Subfield(sf.code, {replace_call})",
                    f"        if sf.code == {lit(code)} else sf",
                    "        for sf in f.subfields",
                    "    ]",
                ],
                {"_re_import"},
                True,
            )
        return (
            [
                f"for f in record.get_fields({lit(tag)}):",
                "    f.subfields = [",
                f"        Subfield(sf.code, {replace_call})",
                f"        if sf.code == {lit(code)} else sf",
                "        for sf in f.subfields",
                "    ]",
            ],
            set(),
            True,  # needs Subfield import from pymarc
        )

    # --- TASK-030: typed ops parity --------------------------------------

    if op.kind == "copy-field":
        src = str(p.get("src_tag", "")).strip()
        dst = str(p.get("dst_tag", "")).strip()
        return (
            [f"copy_field(record, {lit(src)}, {lit(dst)})"],
            {"copy_field"},
            False,
        )

    if op.kind == "move-field":
        src = str(p.get("src_tag", "")).strip()
        dst = str(p.get("dst_tag", "")).strip()
        return (
            [f"move_field(record, {lit(src)}, {lit(dst)})"],
            {"move_field"},
            False,
        )

    if op.kind == "add-subfield":
        tag = str(p.get("tag", "")).strip()
        code = str(p.get("code", "")).strip()
        value = str(p.get("value", ""))
        position = str(p.get("position", "end")).strip() or "end"
        return (
            [
                f"add_subfield_to_fields(record, {lit(tag)}, {lit(code)}, "
                f"{lit(value)}, position={lit(position)})"
            ],
            {"add_subfield_to_fields"},
            False,
        )

    if op.kind == "delete-subfield":
        tag = str(p.get("tag", "")).strip()
        # Accept comma- or space-separated codes; normalize to a list
        # of single-char strings. Empty / whitespace-only entries drop
        # out so a trailing comma doesn't render an empty arg.
        raw_codes = str(p.get("codes", ""))
        codes = [c.strip() for c in re.split(r"[,\s]+", raw_codes) if c.strip()]
        code_args = ", ".join(lit(c) for c in codes) if codes else ""
        if not code_args:
            return (
                [f"# TODO: delete-subfield op {tag!r} has no codes — fill in to enable"],
                set(),
                False,
            )
        return (
            [f"delete_subfields(record, {lit(tag)}, {code_args})"],
            {"delete_subfields"},
            False,
        )

    if op.kind == "copy-subfield":
        tag = str(p.get("tag", "")).strip()
        src_code = str(p.get("src_code", "")).strip()
        dst_code = str(p.get("dst_code", "")).strip()
        return (
            [
                f"copy_subfield_within_field(record, {lit(tag)}, "
                f"{lit(src_code)}, {lit(dst_code)})"
            ],
            {"copy_subfield_within_field"},
            False,
        )

    if op.kind == "edit-indicators":
        tag = str(p.get("tag", "")).strip()
        # Empty-string ind means "leave alone" → pass None. A single
        # space means "set blank" → pass " ".
        raw_ind1 = p.get("ind1")
        raw_ind2 = p.get("ind2")
        ind1_arg = lit(None) if raw_ind1 in (None, "") else lit(str(raw_ind1)[:1])
        ind2_arg = lit(None) if raw_ind2 in (None, "") else lit(str(raw_ind2)[:1])
        return (
            [
                f"set_indicators(record, {lit(tag)}, "
                f"ind1={ind1_arg}, ind2={ind2_arg})"
            ],
            {"set_indicators"},
            False,
        )

    if op.kind == "replace-field-data-by-regex":
        tag = str(p.get("tag", "")).strip()
        pattern = str(p.get("pattern", ""))
        replacement = str(p.get("replacement", ""))
        ignore_case = bool(p.get("ignore_case", False))
        return (
            [
                f"regex_replace_field_data(record, {lit(tag)}, "
                f"{lit(pattern)}, {lit(replacement)}, "
                f"ignore_case={lit(ignore_case)})"
            ],
            {"regex_replace_field_data"},
            False,
        )

    if op.kind == "sort-fields":
        return (["sort_fields(record)"], {"sort_fields"}, False)
    if op.kind == "set-008-form":
        return (["set_008_form_of_item(record)"], {"set_008_form_of_item"}, False)

    if op.kind == "custom":
        code = p.get("code") or ""
        return (code.splitlines() or ["pass"], set(), False)

    # Unknown op kind — render as a no-op + comment so the file stays valid.
    return ([f"# TODO: unknown operation kind {op.kind!r}"], set(), False)


def render_ops_to_python(ops: list[Operation]) -> dict:
    """Render an op list into a task body + the imports it needs.

    Returns `{body, imports}` where:
      * `body` is the function body text (already 4-space indented? NO —
        unindented; callers re-indent per Python conventions);
      * `imports` is the list of import statements to put at module scope.
    """
    body_lines: list[str] = []
    transforms_needed: set[str] = set()
    needs_subfield_import = False
    needs_re_import = False
    for op in ops:
        marker = f"{_OP_MARKER_PREFIX} {op.kind} {json.dumps(op.params, sort_keys=True)}"
        body_lines.append(marker)
        lines, needed, needs_sf = _render_one(op)
        body_lines.extend(lines)
        body_lines.append("")  # blank separator between ops
        # ``_re_import`` is a special marker (not a transforms name)
        # used by ops that emit ``re.compile(...)`` or ``re.sub(...)``
        # in their body. We lift it out before resolving the
        # transforms import set so it doesn't try to import a
        # non-existent ``_re_import`` helper.
        if "_re_import" in needed:
            needs_re_import = True
            needed = needed - {"_re_import"}
        transforms_needed |= needed
        needs_subfield_import = needs_subfield_import or needs_sf

    # Drop the trailing blank line so the rendered body ends cleanly.
    while body_lines and body_lines[-1] == "":
        body_lines.pop()

    imports: list[str] = []
    if needs_re_import:
        imports.append("import re")
    if transforms_needed:
        imports.append(
            "from marcedit_web.lib.transforms import "
            + ", ".join(sorted(transforms_needed))
        )
    if needs_subfield_import:
        imports.append("from pymarc import Subfield")

    return {
        "body": "\n".join(body_lines) or "pass",
        "imports": imports,
    }


# ---------------------------------------------------------------------------
# Parse: existing task body -> ops
# ---------------------------------------------------------------------------


_OP_MARKER_RE = re.compile(
    r"^\s*#\s*OP:\s*(?P<kind>[a-z0-9-]+)\s*(?P<json>\{.*\})?\s*$"
)


def parse_ops_from_source(source: str) -> dict:
    """Extract `Operation` objects from a task body that uses `# OP:` markers.

    `source` is the body text (just the function body, dedented to column 0).
    Returns `{"ops": [...], "form_editable": bool, "reason": str | None}`.

    `form_editable` is False when:
      * no `# OP:` markers are present (e.g. hand-written or pre-migration);
      * any marker has an unparseable JSON payload.

    The caller (gui_runner) decides whether to surface Form view based on
    that flag.
    """
    ops: list[Operation] = []
    found_marker = False
    for line in source.splitlines():
        m = _OP_MARKER_RE.match(line)
        if not m:
            continue
        found_marker = True
        kind = m.group("kind")
        raw_params = m.group("json") or "{}"
        try:
            params = json.loads(raw_params)
        except json.JSONDecodeError:
            return {
                "ops": [],
                "form_editable": False,
                "reason": f"malformed OP marker for {kind!r} — switch to Code view",
            }
        ops.append(Operation(kind=kind, params=params))

    if not found_marker:
        return {
            "ops": [],
            "form_editable": False,
            "reason": (
                "this task was hand-written (or imported) and doesn't carry the "
                "form-builder markers — use Code view to edit"
            ),
        }
    return {"ops": ops, "form_editable": True, "reason": None}
