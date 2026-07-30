"""Leaf deterministic engine for TASK-180 guided value replacement."""

from __future__ import annotations

import re
from typing import Callable, Iterator, Tuple

from pymarc import Field, Record, Subfield


TARGET_KINDS = ("control_field", "subfield", "all_subfields")
MATCH_MODES = (
    "contains",
    "starts_with",
    "ends_with",
    "whole_value",
    "raw_regex",
    "none",
)
REPLACEMENT_MODES = ("matched_text", "whole_value", "prepend", "append")
OCCURRENCE_MODES = ("first", "all")


def validate_request(
    *,
    target_kind: str,
    tag: str,
    subfield: str,
    match_mode: str,
    find: str,
    ignore_case: bool,
    replacement_mode: str,
    replacement: str,
    occurrences: str,
) -> Tuple[str, ...]:
    errors = []
    text_values = {
        "Target type": target_kind,
        "Tag": tag,
        "Subfield code": subfield,
        "Match mode": match_mode,
        "Find": find,
        "Replacement mode": replacement_mode,
        "Replacement": replacement,
        "Occurrence mode": occurrences,
    }
    for label, value in text_values.items():
        if not isinstance(value, str):
            errors.append(label + " must be text.")
    if not isinstance(ignore_case, bool):
        errors.append("Ignore-case setting must be true or false.")
    if errors:
        return tuple(errors)
    if target_kind not in TARGET_KINDS:
        errors.append("Target type is not supported.")
    if not re.fullmatch(r"\d{3}", tag or ""):
        errors.append("Tag must be exactly three numeric characters.")
    elif target_kind == "control_field" and tag not in {
        "001", "002", "003", "004", "005", "006", "007", "008", "009"
    }:
        errors.append("Control-field target must be 001 through 009.")
    elif target_kind != "control_field" and int(tag) < 10:
        errors.append("Subfield target must use tag 010 through 999.")
    if target_kind == "subfield" and not re.fullmatch(
        r"[a-z0-9]", subfield or ""
    ):
        errors.append("Subfield code must be one lowercase letter or digit.")
    if target_kind != "subfield" and subfield:
        errors.append("Subfield code must be empty for this target.")
    if match_mode not in MATCH_MODES:
        errors.append("Match mode is not supported.")
    if replacement_mode not in REPLACEMENT_MODES:
        errors.append("Replacement mode is not supported.")
    if occurrences not in OCCURRENCE_MODES:
        errors.append("Occurrence mode is not supported.")
    if replacement_mode in ("prepend", "append"):
        if match_mode != "none" or find:
            errors.append(
                replacement_mode
                + " requires match mode 'none' and an empty Find value."
            )
        if occurrences != "all":
            errors.append(
                replacement_mode + " requires occurrence mode 'all'."
            )
    elif not find:
        errors.append(
            "Find text is required for {0} replacement.".format(
                "matched-text"
                if replacement_mode == "matched_text"
                else "whole-selected-value"
            )
        )
    elif match_mode == "none":
        errors.append("Match mode 'none' is only valid for prepend or append.")
    if replacement_mode == "whole_value" and occurrences != "first":
        errors.append(
            "Whole-selected-value replacement requires occurrence mode "
            "'first'."
        )
    if (
        replacement_mode == "matched_text"
        and match_mode in ("starts_with", "ends_with", "whole_value")
        and occurrences != "first"
    ):
        errors.append(
            "This anchored match mode requires occurrence mode 'first'."
        )
    if match_mode == "raw_regex" and find:
        try:
            compiled = re.compile(find, re.IGNORECASE if ignore_case else 0)
            compiled.sub(replacement, "")
        except re.error as exc:
            errors.append("Regular expression is invalid: {0}".format(exc))
    return tuple(errors)


def _selected_values(
    record: Record,
    target_kind: str,
    tag: str,
    subfield: str,
) -> Iterator[Tuple[Field, int | None, str]]:
    for field in record.get_fields(tag):
        if target_kind == "control_field":
            yield field, None, field.data or ""
            continue
        for index, selected_subfield in enumerate(field.subfields):
            if (
                target_kind == "all_subfields"
                or selected_subfield.code == subfield
            ):
                yield field, index, selected_subfield.value


def _compile_matcher(
    match_mode: str,
    find: str,
    ignore_case: bool,
) -> re.Pattern:
    if match_mode == "raw_regex":
        pattern = find
    else:
        pattern = re.escape(find)
        if match_mode == "starts_with":
            pattern = "^" + pattern
        elif match_mode == "ends_with":
            pattern += "$"
        elif match_mode == "whole_value":
            pattern = "^" + pattern + "$"
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(pattern, flags)


def _replacement_function(replacement: str) -> Callable[[re.Match], str]:
    return lambda _match: replacement


def _replace_value(
    value: str,
    *,
    matcher: re.Pattern | None,
    match_mode: str,
    replacement_mode: str,
    replacement: str,
    occurrences: str,
) -> Tuple[bool, str, int]:
    if replacement_mode == "prepend":
        return True, replacement + value, 0
    if replacement_mode == "append":
        return True, value + replacement, 0

    assert matcher is not None
    if replacement_mode == "whole_value":
        match = matcher.search(value)
        if match is None:
            return False, value, 0
        new_value = (
            match.expand(replacement)
            if match_mode == "raw_regex"
            else replacement
        )
        return True, new_value, 1

    count = 1 if occurrences == "first" else 0
    replacement_value = (
        replacement
        if match_mode == "raw_regex"
        else _replacement_function(replacement)
    )
    new_value, matched_occurrences = matcher.subn(
        replacement_value,
        value,
        count=count,
    )
    return matched_occurrences > 0, new_value, matched_occurrences


def apply_guided_find_replace(
    record: Record,
    *,
    target_kind: str,
    tag: str,
    subfield: str,
    match_mode: str,
    find: str,
    ignore_case: bool,
    replacement_mode: str,
    replacement: str,
    occurrences: str,
) -> dict:
    errors = validate_request(
        target_kind=target_kind,
        tag=tag,
        subfield=subfield,
        match_mode=match_mode,
        find=find,
        ignore_case=ignore_case,
        replacement_mode=replacement_mode,
        replacement=replacement,
        occurrences=occurrences,
    )
    if errors:
        raise ValueError("; ".join(errors))

    matcher = (
        None
        if match_mode == "none"
        else _compile_matcher(match_mode, find, ignore_case)
    )
    result = {
        "matched_values": 0,
        "changed_values": 0,
        "matched_occurrences": 0,
    }
    for field, subfield_index, value in _selected_values(
        record, target_kind, tag, subfield
    ):
        matched, new_value, matched_occurrences = _replace_value(
            value,
            matcher=matcher,
            match_mode=match_mode,
            replacement_mode=replacement_mode,
            replacement=replacement,
            occurrences=occurrences,
        )
        if not matched:
            continue
        result["matched_values"] += 1
        result["matched_occurrences"] += matched_occurrences
        if new_value == value:
            continue
        result["changed_values"] += 1
        if subfield_index is None:
            field.data = new_value
        else:
            old_subfield = field.subfields[subfield_index]
            field.subfields[subfield_index] = Subfield(
                code=old_subfield.code,
                value=new_value,
            )
    return result
