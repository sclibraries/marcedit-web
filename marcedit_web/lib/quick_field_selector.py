"""Pure, deterministic filter-then-occurrence selection for MARC fields."""

from __future__ import annotations

from dataclasses import dataclass
import re

from pymarc import Field, Record


_INDICATOR_MODES = frozenset({"any", "blank", "exact"})
_MATCH_MODES = frozenset(
    {"exact", "contains", "starts_with", "ends_with", "raw_regex"}
)
_OCCURRENCE_MODES = frozenset({"first", "last", "every", "numbered"})
_MAX_MATCH_CHARS = 1024
_MAX_MATCH_BYTES = 2048


@dataclass(frozen=True)
class IndicatorFilter:
    mode: str = "any"
    value: str = ""


@dataclass(frozen=True)
class FieldFilter:
    tag: str
    ind1: IndicatorFilter = IndicatorFilter()
    ind2: IndicatorFilter = IndicatorFilter()
    subfield_code: str = ""
    match_mode: str = "exact"
    match_value: str = ""
    ignore_case: bool = False

    def __post_init__(self) -> None:
        # Tags and subfield codes come from user-facing controls.  Store their
        # canonical forms once so every caller observes the same selector.
        if isinstance(self.tag, str):
            object.__setattr__(self, "tag", self.tag.strip().upper())
        if isinstance(self.subfield_code, str):
            object.__setattr__(
                self, "subfield_code", self.subfield_code.strip().lower()
            )


@dataclass(frozen=True)
class Occurrence:
    mode: str = "first"
    number: int | None = None


@dataclass(frozen=True)
class FieldSelector:
    field_filter: FieldFilter
    occurrence: Occurrence = Occurrence()


@dataclass(frozen=True)
class SelectionResult:
    fields: tuple[Field, ...]
    skip_reason: str | None = None


def _is_control_tag(tag: str) -> bool:
    return tag.isdigit() and int(tag) <= 9


def _validate_indicator_filter(value: object, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, IndicatorFilter):
        return [f"{label} must be an IndicatorFilter"]
    if not isinstance(value.mode, str) or value.mode not in _INDICATOR_MODES:
        errors.append(f"{label} mode must be any, blank, or exact")
    if not isinstance(value.value, str):
        errors.append(f"{label} value must be text")
    elif isinstance(value.mode, str):
        if value.mode in {"any", "blank"} and value.value:
            errors.append(f"{label} value must be empty for {value.mode}")
        elif value.mode == "exact" and len(value.value) != 1:
            errors.append(f"{label} exact value must be exactly one character")
    return errors


def validate_field_filter(field_filter: object) -> tuple[str, ...]:
    """Return cataloger-facing validation errors for a field filter."""

    if not isinstance(field_filter, FieldFilter):
        return ("field filter must be a FieldFilter",)

    errors: list[str] = []
    tag = field_filter.tag
    if (
        not isinstance(tag, str)
        or len(tag) != 3
        or not tag.isascii()
        or not tag.isdigit()
    ):
        errors.append("tag must be exactly three ASCII digits")
    elif tag == "000":
        errors.append("000 is the leader, not a selectable field tag")

    errors.extend(_validate_indicator_filter(field_filter.ind1, "indicator 1"))
    errors.extend(_validate_indicator_filter(field_filter.ind2, "indicator 2"))

    code = field_filter.subfield_code
    if not isinstance(code, str):
        errors.append("subfield code must be one lowercase letter or digit")
    elif code and (
        len(code) != 1
        or not code.isascii()
        or not code.isalnum()
        or code.lower() != code
    ):
        errors.append("subfield code must be one lowercase letter or digit")

    if (
        not isinstance(field_filter.match_mode, str)
        or field_filter.match_mode not in _MATCH_MODES
    ):
        errors.append("match mode is not supported")
    if not isinstance(field_filter.match_value, str):
        errors.append("match value must be text")
    else:
        if len(field_filter.match_value) > _MAX_MATCH_CHARS:
            errors.append("match value must be at most 1,024 characters")
        if len(field_filter.match_value.encode("utf-8")) > _MAX_MATCH_BYTES:
            errors.append("match value must be at most 2,048 bytes")
        if (
            code
            and field_filter.match_value == ""
            and field_filter.match_mode != "raw_regex"
        ):
            errors.append(
                "match value must be nonempty when a subfield code is selected"
            )
        if not code and field_filter.match_value:
            errors.append("match value requires a subfield code")
        if not code and field_filter.match_mode != "exact":
            errors.append("match mode requires a subfield code")
    if not isinstance(field_filter.ignore_case, bool):
        errors.append("ignore_case must be true or false")

    if isinstance(tag, str) and tag and _is_control_tag(tag):
        if (
            isinstance(field_filter.ind1, IndicatorFilter)
            and field_filter.ind1.mode != "any"
        ):
            errors.append("control fields cannot use indicator filters")
        if (
            isinstance(field_filter.ind2, IndicatorFilter)
            and field_filter.ind2.mode != "any"
        ):
            errors.append("control fields cannot use indicator filters")
        if code:
            errors.append("control fields cannot use subfield filters")
    return tuple(errors)


def validate_selector(
    selector: object, *, allow_every: bool = True
) -> tuple[str, ...]:
    """Return cataloger-facing errors for a selector and occurrence choice."""

    if not isinstance(selector, FieldSelector):
        return ("selector must be a FieldSelector",)
    errors = list(validate_field_filter(selector.field_filter))
    occurrence = selector.occurrence
    if not isinstance(occurrence, Occurrence):
        errors.append("occurrence must be an Occurrence")
        return tuple(errors)
    if not isinstance(occurrence.mode, str) or occurrence.mode not in _OCCURRENCE_MODES:
        errors.append("occurrence mode is not supported")
    elif occurrence.mode == "every" and not allow_every:
        errors.append("every matching field is not allowed for this operation")
    if occurrence.mode == "numbered":
        if isinstance(occurrence.number, bool) or not isinstance(
            occurrence.number, int
        ):
            errors.append("numbered occurrence requires an integer number")
        elif not 1 <= occurrence.number <= 999:
            errors.append("numbered occurrence must be between 1 and 999")
    elif occurrence.number is not None:
        errors.append("occurrence number is only valid for numbered occurrence")
    return tuple(errors)


def _indicator_matches(candidate: str, criterion: IndicatorFilter) -> bool:
    if criterion.mode == "any":
        return True
    if criterion.mode == "blank":
        return candidate == " "
    return candidate == criterion.value


def _value_matches(
    candidate: str, field_filter: FieldFilter, regex: re.Pattern[str] | None
) -> bool:
    if field_filter.match_mode == "raw_regex":
        return regex.search(candidate) is not None  # type: ignore[union-attr]
    expected = field_filter.match_value
    if field_filter.ignore_case:
        candidate = candidate.casefold()
        expected = expected.casefold()
    if field_filter.match_mode == "exact":
        return candidate == expected
    if field_filter.match_mode == "contains":
        return expected in candidate
    if field_filter.match_mode == "starts_with":
        return candidate.startswith(expected)
    return candidate.endswith(expected)


def matching_fields(record: Record, field_filter: FieldFilter) -> tuple[Field, ...]:
    """Return fields passing ``field_filter`` in their original record order."""

    errors = validate_field_filter(field_filter)
    if errors:
        raise ValueError("; ".join(errors))

    regex: re.Pattern[str] | None = None
    if field_filter.match_mode == "raw_regex":
        flags = re.IGNORECASE if field_filter.ignore_case else 0
        try:
            # Raw expressions are compiled at the sandbox-facing matching
            # boundary, never while constructing or rendering a request.
            regex = re.compile(field_filter.match_value, flags)
        except re.error as exc:
            raise ValueError("raw regular expression is invalid: " + str(exc)) from exc

    selected: list[Field] = []
    for field in record.fields:
        if field.tag != field_filter.tag:
            continue
        if field.is_control_field():
            # Validation prevents non-default control-field predicates.  This
            # guard keeps matching safe if a custom Field implementation lies
            # about its tag/control shape.
            if (
                field_filter.ind1.mode != "any"
                or field_filter.ind2.mode != "any"
                or field_filter.subfield_code
            ):
                raise ValueError(
                    "control fields cannot use indicator or subfield filters"
                )
            selected.append(field)
            continue
        if not _indicator_matches(field.indicators[0], field_filter.ind1):
            continue
        if not _indicator_matches(field.indicators[1], field_filter.ind2):
            continue
        if field_filter.subfield_code:
            values = field.get_subfields(field_filter.subfield_code)
            if not any(_value_matches(value, field_filter, regex) for value in values):
                continue
        selected.append(field)
    return tuple(selected)


def resolve_fields(record: Record, selector: FieldSelector) -> SelectionResult:
    """Filter a record, then resolve its requested occurrence deterministically."""

    errors = validate_selector(selector)
    if errors:
        raise ValueError("; ".join(errors))
    filtered = matching_fields(record, selector.field_filter)
    if not filtered:
        return SelectionResult((), "no-filtered-fields")

    occurrence = selector.occurrence
    if occurrence.mode == "first":
        return SelectionResult((filtered[0],))
    if occurrence.mode == "last":
        return SelectionResult((filtered[-1],))
    if occurrence.mode == "every":
        return SelectionResult(filtered)
    assert occurrence.number is not None
    if occurrence.number > len(filtered):
        return SelectionResult((), "numbered-occurrence-absent")
    return SelectionResult((filtered[occurrence.number - 1],))


def _describe_indicator(position: int, criterion: IndicatorFilter) -> str | None:
    if criterion.mode == "any":
        return None
    if criterion.mode == "blank":
        return f"indicator {position} is MARC blank"
    return f"indicator {position} is '{criterion.value}'"


def describe_selector(selector: FieldSelector) -> str:
    """Describe a valid selector in deterministic, cataloger-facing language."""

    errors = validate_selector(selector)
    if errors:
        raise ValueError("; ".join(errors))
    field_filter = selector.field_filter
    conditions: list[str] = []
    for position, criterion in ((1, field_filter.ind1), (2, field_filter.ind2)):
        description = _describe_indicator(position, criterion)
        if description:
            conditions.append(description)
    if field_filter.subfield_code:
        mode_labels = {
            "exact": "equals",
            "contains": "contains",
            "starts_with": "starts with",
            "ends_with": "ends with",
            "raw_regex": "matches regular expression",
        }
        mode_label = mode_labels[field_filter.match_mode]
        value = field_filter.match_value
        if field_filter.match_mode == "raw_regex":
            text = (
                f"subfield ${field_filter.subfield_code} matches regular expression "
                f"'{value}'"
            )
        else:
            text = f"subfield ${field_filter.subfield_code} {mode_label} '{value}'"
        if field_filter.ignore_case:
            text += " (case-insensitive)"
        conditions.append(text)
    if conditions:
        result = f"{field_filter.tag} fields where " + ", ".join(conditions)
    else:
        result = f"{field_filter.tag} fields"
    occurrence = selector.occurrence
    if occurrence.mode == "first":
        occurrence_text = "first"
    elif occurrence.mode == "last":
        occurrence_text = "last"
    elif occurrence.mode == "every":
        occurrence_text = "every matching field"
    else:
        occurrence_text = f"numbered occurrence {occurrence.number}"
    return result + "; select " + occurrence_text
