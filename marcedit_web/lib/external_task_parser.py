"""Strict parsing for supported external MarcEdit task instructions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


class ExternalParseError(ValueError):
    """Raised when an external instruction is not structurally valid."""


@dataclass(frozen=True)
class ExternalInstruction:
    verb: str
    arguments: tuple[str, ...]
    source_line: str
    source_entry: str
    line_number: int
    instruction_sha256: str
    option_code: int | None = None
    boolean_flags: tuple[bool, ...] = ()


_ARGUMENT_COUNTS = {
    "ADD": (4, 4),
    "COPY": (7, 7),
    "DELETE": (8, 8),
    "EDITFIELD": (5, 5),
    "RDAHELPER": (1, 1),
    "REPLACE": (5, 6),
    "SORTBY": (3, 3),
    "SUBFIELD_EDIT": (5, 5),
    "SUBFIELD_REMOVE": (4, 4),
    "buildnewfield": (5, 5),
}


def _require_integer(
    value: str,
    *,
    label: str,
    accepted: set[int],
) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ExternalParseError(f"{label} must be an integer")
    decoded = int(value)
    if decoded not in accepted:
        supported = ", ".join(str(item) for item in sorted(accepted))
        raise ExternalParseError(
            f"{label} {decoded} is unsupported; expected one of {supported}"
        )
    return decoded


def _require_boolean(value: str, *, label: str) -> bool:
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ExternalParseError(f"{label} must be True or False")


def _pipe_option(value: str, *, label: str, accepted: set[int]) -> int:
    parts = value.split("|")
    if len(parts) != 2:
        raise ExternalParseError(f"{label} must contain two pipe-delimited integers")
    option = _require_integer(parts[0], label=label, accepted=accepted)
    _require_integer(parts[1], label=f"{label} suffix", accepted={0})
    return option


def _decode_options(
    verb: str, arguments: tuple[str, ...]
) -> tuple[int | None, tuple[bool, ...]]:
    if verb == "ADD":
        return _require_integer(
            arguments[2], label="ADD option", accepted={100, 101, 106, 108}
        ), ()
    if verb == "COPY":
        return None, (
            _require_boolean(arguments[2], label="COPY flag 1"),
            _require_boolean(arguments[5], label="COPY flag 2"),
        )
    if verb == "DELETE":
        return (
            _require_integer(arguments[2], label="DELETE option", accepted={0}),
            tuple(
                _require_boolean(value, label=f"DELETE flag {index}")
                for index, value in enumerate(arguments[3:8], start=1)
            ),
        )
    if verb == "EDITFIELD":
        return _require_integer(
            arguments[2], label="EDITFIELD option", accepted={0}
        ), ()
    if verb == "REPLACE":
        option_code = _require_integer(
            arguments[2], label="REPLACE option 1", accepted={0, 2}
        )
        _require_integer(
            arguments[4], label="REPLACE option 2", accepted={0, 1, 2}
        )
        flags = (
            (_require_boolean(arguments[5], label="REPLACE flag 1"),)
            if len(arguments) >= 6
            else ()
        )
        return option_code, flags
    if verb == "SORTBY":
        return None, tuple(
            _require_boolean(value, label=f"SORTBY flag {index}")
            for index, value in enumerate(arguments[1:3], start=1)
        )
    if verb == "SUBFIELD_EDIT":
        return _pipe_option(
            arguments[4], label="SUBFIELD_EDIT option", accepted={0, 101}
        ), ()
    if verb == "SUBFIELD_REMOVE":
        return _pipe_option(
            arguments[3], label="SUBFIELD_REMOVE option", accepted={107}
        ), ()
    if verb == "buildnewfield":
        return None, tuple(
            _require_boolean(value, label=f"Build Field flag {index}")
            for index, value in enumerate(arguments[1:5], start=1)
        )
    return None, ()


def parse_instruction(
    source_line: str,
    *,
    source_entry: str = "",
    line_number: int = 0,
) -> ExternalInstruction:
    normalized = source_line.rstrip("\r\n")
    parts = normalized.split("\t")
    if not parts or not parts[0].strip():
        raise ExternalParseError("instruction verb is required")

    verb = parts[0].strip()
    if verb not in _ARGUMENT_COUNTS:
        raise ExternalParseError(f"unsupported instruction verb {verb!r}")

    arguments = tuple(parts[1:])
    minimum, maximum = _ARGUMENT_COUNTS[verb]
    if len(arguments) < minimum:
        raise ExternalParseError(
            f"{verb} requires at least {minimum} argument columns; got {len(arguments)}"
        )
    for index, value in enumerate(arguments[maximum:], start=maximum + 1):
        if value:
            raise ExternalParseError(f"{verb} has nonempty surplus column {index}")

    option_code, boolean_flags = _decode_options(verb, arguments[:maximum])
    if verb == "RDAHELPER" and len(arguments[0].split("|")) != 18:
        raise ExternalParseError("RDAHELPER requires 18 pipe-delimited positions")

    return ExternalInstruction(
        verb=verb,
        arguments=arguments,
        source_line=normalized,
        source_entry=source_entry,
        line_number=line_number,
        instruction_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        option_code=option_code,
        boolean_flags=boolean_flags,
    )


def instruction_shape(value: ExternalInstruction) -> str:
    """Return a value-neutral compatibility shape identifier."""
    if (
        value.verb == "SUBFIELD_EDIT"
        and value.option_code == 0
        and value.arguments[2]
        and not value.arguments[2].startswith("^")
    ):
        return "subfield-edit-literal"
    return f"{value.verb.replace('_', '-').lower()}-unrecognized"
