"""Deterministic parser for cataloger notes into task draft reviews."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from marcedit_web.lib import ai_task_draft, editor

_TAG = r"\d{3}"


@dataclass(frozen=True)
class _Block:
    heading: str
    lines: list[str]


def draft_task_from_notes(notes: str) -> ai_task_draft.DraftReview:
    """Parse supported cataloger-note patterns into a validated draft."""
    draft = _empty_draft(_derive_task_name(notes), _derive_description(notes))
    for block in _blocks(notes):
        _parse_block(block, draft)
    return ai_task_draft.parse_ai_task_draft(json.dumps(draft))


def help_text() -> str:
    """Return concise user-facing examples for deterministic drafting."""
    return (
        "Use one instruction per line for best results.\n"
        "Task: routledge-eba\n"
        'replace field 001 "^TFeba" with "SCTFEBA"\n'
        'replace subfield 856 u "http://old" with "https://new"\n'
        "change subfield 856 z to y\n"
        "add field 710 2_ $aRoutledge EBA\n"
        "add field 852 8_ $hOnline $bSmith College Online\n"
        "delete tag 029\n"
        "Use _ or \\ for blank indicators. Ambiguous lines stay in review."
    )


def unresolved_text(review: ai_task_draft.DraftReview) -> str:
    """Return unresolved review text suitable for optional Gemini fallback."""
    parts = list(review.questions) + list(review.unsupported_lines)
    parts.extend(
        op.source_text or op.reason for op in review.rejected_operations
    )
    return "\n".join(part for part in parts if part)


def merge_fallback_review(
    base: ai_task_draft.DraftReview,
    fallback: ai_task_draft.DraftReview,
) -> ai_task_draft.DraftReview:
    """Merge a fallback review into a deterministic draft."""
    return ai_task_draft.DraftReview(
        task_name=base.task_name,
        operations=base.operations + fallback.operations,
        rejected_operations=fallback.rejected_operations,
        questions=fallback.questions,
        manual_notes=base.manual_notes + fallback.manual_notes,
        unsupported_lines=fallback.unsupported_lines,
        description=base.description or fallback.description,
    )


def _empty_draft(task_name: str, description: str) -> dict:
    return {
        "task_name": task_name,
        "description": description,
        "operations": [],
        "questions": [],
        "manual_notes": [],
        "unsupported_lines": [],
    }


def _derive_task_name(notes: str) -> str:
    for raw in notes.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("task:"):
            line = line.split(":", 1)[1].strip()
        elif _is_structural_heading(line) or _is_instruction_detail(line):
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", line.lower()).strip("-")
        if editor.is_valid_slug(slug):
            return slug
    return "draft-from-notes"


def _derive_description(notes: str) -> str:
    for raw in notes.splitlines():
        line = raw.strip()
        if line.lower().startswith("description:"):
            return line.split(":", 1)[1].strip()
    for raw in notes.splitlines():
        line = raw.strip()
        if line and not line.lower().startswith("task:"):
            return f"{line} task draft"
    return "Task draft from notes"


def _blocks(notes: str) -> list[_Block]:
    blocks: list[_Block] = []
    current: _Block | None = None
    for raw in notes.splitlines():
        line = raw.strip()
        if not line or set(line) == {"-"}:
            continue
        if _is_heading(line):
            if current is not None:
                blocks.append(current)
            current = _Block(line, [])
        elif current is None:
            blocks.append(_Block(line, []))
        else:
            current.lines.append(line)
    if current is not None:
        blocks.append(current)
    return blocks


def _is_heading(line: str) -> bool:
    lower = line.lower()
    return (
        lower.startswith(("task:", "description:"))
        or _is_structural_heading(line)
        or bool(re.match(r"^(add field|edit field|edit subfield)\s*\(\d{3}\)", lower))
        or lower.startswith("edit subfield")
        or lower.startswith(
            (
                "replace field ",
                "replace subfield ",
                "change subfield ",
                "add field ",
                "delete tag ",
            )
        )
        or "lastpass" in lower
        or "core custom catalog" in lower
        or "remove blank subfields" in lower
    )


def _is_structural_heading(line: str) -> bool:
    return line.lower() in {"find/replace", "manual marcedit tasks"}


def _is_instruction_detail(line: str) -> bool:
    return (
        line.startswith(("$", "="))
        or bool(re.match(r"^\d{3}$", line))
        or bool(re.match(r"^\d?\\?\$[0-9a-z]", line))
    )


def _parse_block(block: _Block, draft: dict) -> None:
    line = block.heading.strip()
    lower = line.lower()
    if lower.startswith(("task:", "description:")):
        return
    if "lastpass" in lower or "ftp login" in lower:
        draft["manual_notes"].append(line)
        return
    if "core custom catalog" in lower:
        draft["questions"].append(line)
        return
    if "remove blank subfields" in lower:
        draft["unsupported_lines"].append(line)
        return
    if lower.startswith("replace field "):
        _parse_replace_field(line, draft)
        return
    if lower.startswith("replace subfield "):
        _parse_replace_subfield(line, draft)
        return
    if lower.startswith("change subfield "):
        _parse_change_subfield(line, draft)
        return
    if lower.startswith("add field ") and not re.match(r"add field\s*\(", lower):
        _parse_add_field_line(line, draft)
        return
    if lower.startswith("delete tag "):
        tag = line.split()[-1]
        _add_op(draft, "delete-tag", {"tag": tag}, line, f"Delete tag {tag}.")
        return
    if lower.startswith("add field"):
        _parse_add_field_block(block, draft)
        return
    if lower.startswith("edit field"):
        _parse_edit_field_block(block, draft)
        return
    if lower == "find/replace":
        _parse_find_replace_block(block, draft)
        return
    if lower.startswith("edit subfield"):
        draft["unsupported_lines"].append(_block_text(block))
        return
    draft["unsupported_lines"].append(_block_text(block))


def _parse_replace_field(line: str, draft: dict) -> None:
    match = re.match(rf'replace field ({_TAG}) "(.+)" with "(.*)"$', line, re.I)
    if match is None:
        draft["unsupported_lines"].append(line)
        return
    tag, pattern, replacement = match.groups()
    _add_regex_op(draft, tag, pattern, replacement, line, f"Replace {tag} by regex.")


def _parse_replace_subfield(line: str, draft: dict) -> None:
    match = re.match(
        rf'replace subfield ({_TAG}) ([0-9a-z]) "(.*)" with "(.*)"$',
        line,
        re.I,
    )
    if match is None:
        draft["unsupported_lines"].append(line)
        return
    tag, code, find, replacement = match.groups()
    _add_op(
        draft,
        "subfield-replace",
        {
            "tag": tag,
            "code": code,
            "find": find,
            "replace": replacement,
            "regex": False,
            "ignore_case": False,
        },
        line,
        f"Replace text in {tag}${code}.",
    )


def _parse_change_subfield(line: str, draft: dict) -> None:
    match = re.match(rf"change subfield ({_TAG}) ([0-9a-z]) to ([0-9a-z])$", line, re.I)
    if match is None:
        draft["unsupported_lines"].append(line)
        return
    tag, src, dst = match.groups()
    _add_op(
        draft,
        "copy-subfield",
        {"tag": tag, "src_code": src, "dst_code": dst},
        line,
        f"Copy {tag}${src} to ${dst}.",
    )
    _add_op(
        draft,
        "delete-subfield",
        {"tag": tag, "codes": src},
        line,
        f"Remove original {tag}${src}.",
    )


def _parse_add_field_line(line: str, draft: dict) -> None:
    match = re.match(rf"add field ({_TAG})\s+(\S{{2}})\s+(.+)$", line, re.I)
    if match is None:
        draft["unsupported_lines"].append(line)
        return
    tag, indicators, sf_text = match.groups()
    _add_field_from_text(draft, tag, indicators, sf_text, line, "high")


def _parse_add_field_block(block: _Block, draft: dict) -> None:
    match = re.search(r"\((\d{3})\)", block.heading)
    tag = match.group(1) if match else (block.lines[0] if block.lines else "")
    field_text = block.lines[-1] if block.lines else ""
    if not re.fullmatch(_TAG, tag) or not field_text:
        draft["unsupported_lines"].append(_block_text(block))
        return
    _add_field_from_text(
        draft,
        tag,
        field_text[:2],
        field_text[2:],
        _block_text(block),
        "medium",
    )


def _parse_edit_field_block(block: _Block, draft: dict) -> None:
    match = re.search(r"\((\d{3})\)", block.heading)
    tag = match.group(1) if match else ""
    values = [line for line in block.lines if line != tag]
    if tag and len(values) == 2:
        _add_regex_op(
            draft,
            tag,
            f"^{re.escape(values[0])}",
            values[1],
            _block_text(block),
            f"Replace {tag} prefix.",
            "medium",
        )
        return
    draft["unsupported_lines"].append(_block_text(block))


def _parse_find_replace_block(block: _Block, draft: dict) -> None:
    if len(block.lines) != 2:
        draft["unsupported_lines"].append(_block_text(block))
        return
    src, dst = (_clean_find_replace_value(line) for line in block.lines)
    if src.startswith("$z") and dst.startswith("$y") and src[2:] == dst[2:]:
        _add_op(
            draft,
            "copy-subfield",
            {"tag": "856", "src_code": "z", "dst_code": "y"},
            _block_text(block),
            "Change 856 subfield z link text to subfield y.",
            "medium",
        )
        _add_op(
            draft,
            "delete-subfield",
            {"tag": "856", "codes": "z"},
            _block_text(block),
            "Remove original 856 subfield z.",
            "medium",
        )
        return
    if "libproxy.smith.edu" in src and "libproxy.smith.edu" in dst:
        _add_op(
            draft,
            "subfield-replace",
            {
                "tag": "856",
                "code": "u",
                "find": src,
                "replace": dst,
                "regex": False,
                "ignore_case": False,
            },
            _block_text(block),
            "Update Smith proxy URL in 856$u.",
            "medium",
        )
        return
    draft["unsupported_lines"].append(_block_text(block))


def _clean_find_replace_value(value: str) -> str:
    return re.sub(r"\s+\([^)]*\)\s*$", "", value).strip()


def _add_field_from_text(
    draft: dict,
    tag: str,
    indicators: str,
    sf_text: str,
    source: str,
    confidence: str,
) -> None:
    ind1, ind2 = _parse_indicators(indicators)
    subfields = _parse_subfields(sf_text)
    if not subfields:
        draft["unsupported_lines"].append(source)
        return
    _add_op(
        draft,
        "add-field",
        {
            "tag": tag,
            "ind1": ind1,
            "ind2": ind2,
            "subfields": subfields,
            "condition": "always",
            "if_absent": False,
        },
        source,
        f"Add field {tag}.",
        confidence,
    )


def _parse_indicators(text: str) -> tuple[str, str]:
    chars = (text + "__")[:2]
    first, second = chars[0], chars[1]
    return (_indicator_char(first), _indicator_char(second))


def _indicator_char(char: str) -> str:
    return " " if char in {"_", "\\"} else char


def _parse_subfields(text: str) -> list[list[str]]:
    parts = re.split(r"\$([0-9a-z])", text)
    out: list[list[str]] = []
    for i in range(1, len(parts), 2):
        value = parts[i + 1].strip()
        if value:
            out.append([parts[i], value])
    return out


def _add_regex_op(
    draft: dict,
    tag: str,
    pattern: str,
    replacement: str,
    source: str,
    explanation: str,
    confidence: str = "high",
) -> None:
    _add_op(
        draft,
        "replace-field-data-by-regex",
        {
            "tag": tag,
            "pattern": pattern,
            "replacement": replacement,
            "ignore_case": False,
        },
        source,
        explanation,
        confidence,
        {
            "pattern": pattern,
            "meaning": f"Matches {pattern} in {tag}.",
            "before": pattern.lstrip("^"),
            "after": replacement,
        },
    )


def _add_op(
    draft: dict,
    kind: str,
    params: dict,
    source: str,
    explanation: str,
    confidence: str = "high",
    regex: dict | None = None,
) -> None:
    op = {
        "kind": kind,
        "params": params,
        "source_text": source,
        "explanation": explanation,
        "confidence": confidence,
    }
    if regex is not None:
        op["regex"] = regex
    draft["operations"].append(op)


def _block_text(block: _Block) -> str:
    return "\n".join([block.heading] + block.lines)
