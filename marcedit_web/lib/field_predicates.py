"""Validated structural selection for individual MARC fields."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pymarc import Field


_PREDICATE_KEYS = {
    "ind1", "ind2", "ind1_not", "ind2_not", "subfield_matches"
}
_MATCH_KEYS = {"code", "mode", "value", "ignore_case"}
_MATCH_MODES = {
    "exact",
    "contains",
    "starts_with",
    "ends_with",
    "exists",
    "regex",
}


def validate_field_predicate(value: object) -> tuple[str, ...]:
    """Return all structural errors in one field predicate."""

    if not isinstance(value, Mapping):
        return ("field predicate must be an object",)
    if not value:
        return ("field predicate must contain at least one condition",)
    errors = []
    unknown = sorted(set(value) - _PREDICATE_KEYS)
    if unknown:
        errors.append("unknown predicate key: {0}".format(", ".join(unknown)))
    for name in ("ind1", "ind2", "ind1_not", "ind2_not"):
        if name in value and (
            not isinstance(value[name], str) or len(value[name]) != 1
        ):
            errors.append("{0} must be exactly one character".format(name))
    for position in ("ind1", "ind2"):
        negative = position + "_not"
        if (
            position in value
            and negative in value
            and value[position] == value[negative]
        ):
            errors.append("{0} conditions are contradictory".format(position))
    if "subfield_matches" in value:
        matches = value["subfield_matches"]
        if not isinstance(matches, list) or not matches:
            errors.append("subfield_matches must contain at least one match")
        else:
            for index, match in enumerate(matches, start=1):
                label = "subfield match {0}".format(index)
                if not isinstance(match, Mapping):
                    errors.append(label + " must be an object")
                    continue
                unexpected = sorted(set(match) - _MATCH_KEYS)
                missing = sorted(_MATCH_KEYS - set(match))
                if unexpected:
                    errors.append(
                        label + " contains unknown keys: " + ", ".join(unexpected)
                    )
                if missing:
                    errors.append(label + " requires: " + ", ".join(missing))
                code = match.get("code")
                if (
                    not isinstance(code, str)
                    or len(code) != 1
                    or not code.isascii()
                    or not code.isalnum()
                    or code.lower() != code
                ):
                    errors.append(
                        label + " code must be one lowercase letter or digit"
                    )
                if match.get("mode") not in _MATCH_MODES:
                    errors.append(label + " mode is not supported")
                match_value = match.get("value")
                if not isinstance(match_value, str) or match_value == "":
                    errors.append(label + " value must be nonempty text")
                elif match.get("mode") == "exists" and match_value != "*":
                    errors.append(label + " exists mode value must be '*'")
                elif match.get("mode") == "regex":
                    try:
                        re.compile(match_value)
                    except re.error as exc:
                        errors.append(label + " regex is invalid: " + str(exc))
                if not isinstance(match.get("ignore_case"), bool):
                    errors.append(label + " ignore_case must be true or false")
    return tuple(errors)


def _value_matches(candidate: str, criterion: Mapping[str, Any]) -> bool:
    expected = criterion["value"]
    mode = criterion["mode"]
    if mode == "exists":
        return True
    if mode == "regex":
        flags = re.IGNORECASE if criterion["ignore_case"] else 0
        return re.search(expected, candidate, flags) is not None
    if criterion["ignore_case"]:
        candidate = candidate.casefold()
        expected = expected.casefold()
    if mode == "exact":
        return candidate == expected
    if mode == "contains":
        return expected in candidate
    if mode == "starts_with":
        return candidate.startswith(expected)
    return candidate.endswith(expected)


def field_matches(field: Field, predicate: Mapping[str, Any]) -> bool:
    """Return whether one data field satisfies every predicate condition."""

    errors = validate_field_predicate(predicate)
    if errors:
        raise ValueError("; ".join(errors))
    if field.is_control_field():
        raise ValueError(
            "control fields cannot use indicator or subfield predicates"
        )
    for position, index in (("ind1", 0), ("ind2", 1)):
        if (
            position in predicate
            and field.indicators[index] != predicate[position]
        ):
            return False
        negative = position + "_not"
        if (
            negative in predicate
            and field.indicators[index] == predicate[negative]
        ):
            return False
    for criterion in predicate.get("subfield_matches", []):
        if not any(
            _value_matches(value, criterion)
            for value in field.get_subfields(criterion["code"])
        ):
            return False
    return True
