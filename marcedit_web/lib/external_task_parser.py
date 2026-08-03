"""Strict parsing for supported external MarcEdit task instructions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ExternalParseError(ValueError):
    """An immutable structural failure with source provenance."""

    message: str
    failure_code: str
    source_line: str = ""
    source_entry: str = ""
    line_number: int = 0
    instruction_sha256: str = ""
    verb: str = ""
    arguments: tuple[str, ...] = ()
    failing_column: int | None = None
    failing_position: int | None = None

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)

    def with_context(
        self,
        *,
        source_line: str,
        source_entry: str,
        line_number: int,
        instruction_sha256: str,
        verb: str,
        arguments: tuple[str, ...],
    ) -> ExternalParseError:
        return replace(
            self,
            source_line=source_line,
            source_entry=source_entry,
            line_number=line_number,
            instruction_sha256=instruction_sha256,
            verb=verb,
            arguments=arguments,
        )


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


RDA_SWITCH_POSITIONS = (*range(1, 17), 18)

_CHARACTERIZED_DELETE_REGEX_DIGESTS = frozenset({
    # Local reviewed corpus signature; value stays local and untracked.
    "1185f92d1738b5922634312502c0f10bf8fbc44321e1eb4d53a895a3d456ccec",
    # Sanitized equivalence fixture: 9\$a(ABC).
    "f09101eaf438583b9c258a36ff2c3e1f139154ff204c497be9634030b362ae70",
})

_CHARACTERIZED_REPLACE_SHAPES = {
    "e25d8ab4c2ba4d894214072117d790c68a66090063a4028356a03170c16536c8": "replace-008-form-23",
    "fc2b0810f87e01bb1fd33a3333f377d794159c63e5c8cc49907a5d1e4ec5038f": "replace-008-form-29",
    "0fe0d6b95234500d441f35d66f471fd9cfee2c1e455202e5f48bad85a074f171": "replace-856-stage",
    "dcf09ea2b281af15bb66a0abf2b725535dc68861441dae0a2a8906738a8c01fe": "replace-956-restore",
    "1b3a03c559cc5e12f6a7b828b9302a6c1a249907b5e7063cf0fa3c4efddc6b69": "replace-008-blank-29",
    # Sanitized fixture and reviewed local-corpus digest for the same shape.
    "7d3dbd4bfbc4b5730e4100c0b120e3d6fd797e3637e4f34442553c9779c638dc": "replace-035-prefix",
    "8b2caa917fa54c724f7d9996bf6a51c399f8933705089404f1ab0a3460ad5ed1": "replace-035-prefix",
    "44f69f7a80508d1ec03ddf43a0a55d83916fab4c2232ffc26d5bc0e9ec75b758": "replace-035-oclc",
    "8e56d6bb7717fd3ab6c2f7cc6cabe59ba2de12feb59b307bfcd3f5e59689e4da": "replace-336-order-a",
    "ec07c2a68fee8e35a7033ba8d71a2e36d847ec9be99ee9b7c17e05ef88b4fc76": "replace-336-order-b",
    "bb44fc023abeb4ae1678cd6362a1f9b041fb2592368784b4ef270c3c300764b1": "replace-337-order-a",
    "1b056c7cdd52df843dde2cbde324b00341ed68b3fbdc911691776ba12c3a32c9": "replace-337-order-b",
    "570e990ea5b3b2c4fb9db04e3e3d2d07a3430249380605645d56e156ef7f982a": "replace-338-order-a",
    "db375812f671a1acecebd4d16ef4a3a923ed7a742200f7da02779a7ba57731e5": "replace-338-order-b",
    # Sanitized fixture and reviewed local-corpus digest for the same shape.
    "7ed273cc96bcd65f303ae4ead9f6cc099e02d150d6867d9cd4353ccd5ce67099": "replace-852-normalize",
    "c2674288403fe464963e1ed2501d937e229a7d8df4f11969ab4b56b55335439a": "replace-852-normalize",
}


def characterized_replace_shape(instruction_sha256: str) -> str | None:
    """Return the exact reviewed REPLACE shape for one normalized digest."""

    return _CHARACTERIZED_REPLACE_SHAPES.get(instruction_sha256)

RDA_OPTION_LABELS = {
    1: "Add MARC 336 Content Type",
    2: "Add MARC 337 Media Type and 338 Carrier Type",
    3: "Add MARC 344 Sound Characteristics",
    4: "Add MARC 345 Projection Characteristics",
    5: "Add MARC 346 Video Characteristics",
    6: "Add MARC 347 Digital File Characteristics",
    7: "Add MARC 380 Form of Work",
    8: "Add MARC 381 Other Distinguishing Characteristics",
    9: "Evaluate MARC 260/264 publication fields",
    10: "Always use copyright and phonogram symbols",
    11: "Add qualifying information to MARC 015/020/024/027",
    12: "Modify MARC 040 to add $e rda",
    13: "Process MARC 502 dissertation notes",
    14: "Delete the General Material Designation from MARC 245 $h",
    15: "Generate a General Material Designation",
    16: "Expand RDA abbreviations",
    18: "Add a relator term in MARC 100 $e",
}


def is_characterized_delete_mnemonic_regex(
    tag: str,
    match: str,
    flags: tuple[bool, ...],
) -> bool:
    """Return whether DELETE uses one exact reviewed mnemonic regex."""

    return (
        tag == "035"
        and flags == (True, False, False, False, False)
        and hashlib.sha256(match.encode("utf-8")).hexdigest()
        in _CHARACTERIZED_DELETE_REGEX_DIGESTS
    )


def enabled_rda_option_labels(flags: tuple[bool, ...]) -> tuple[str, ...]:
    """Translate typed RDA switches to their cataloger-facing option names."""

    if len(flags) != len(RDA_SWITCH_POSITIONS):
        raise ValueError("RDAHELPER typed switches are incomplete")
    return tuple(
        RDA_OPTION_LABELS[position]
        for position, enabled in zip(RDA_SWITCH_POSITIONS, flags)
        if enabled
    )


def rda_option_label(position: int) -> str:
    """Return the cataloger-facing name for one serialized switch."""

    try:
        return RDA_OPTION_LABELS[position]
    except KeyError as exc:
        raise ValueError("RDAHELPER switch is not recognized") from exc


def _require_integer(
    value: str,
    *,
    label: str,
    accepted: set[int],
    column: int,
) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ExternalParseError(
            f"{label} must be an integer",
            failure_code="invalid_integer",
            failing_column=column,
        )
    decoded = int(value)
    if decoded not in accepted:
        supported = ", ".join(str(item) for item in sorted(accepted))
        raise ExternalParseError(
            f"{label} {decoded} is unsupported; expected one of {supported}",
            failure_code="unsupported_option",
            failing_column=column,
        )
    return decoded


def _require_boolean(value: str, *, label: str, column: int) -> bool:
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ExternalParseError(
        f"{label} must be True or False",
        failure_code="invalid_boolean",
        failing_column=column,
    )


def _pipe_option(
    value: str,
    *,
    label: str,
    accepted: set[int],
    column: int,
) -> int:
    parts = value.split("|")
    if len(parts) != 2:
        raise ExternalParseError(
            f"{label} must contain two pipe-delimited integers",
            failure_code="invalid_pipe_option",
            failing_column=column,
        )
    option = _require_integer(
        parts[0], label=label, accepted=accepted, column=column
    )
    _require_integer(
        parts[1],
        label=f"{label} suffix",
        accepted={0},
        column=column,
    )
    return option


def _decode_rda_flags(value: str) -> tuple[bool, ...]:
    positions = value.split("|")
    if len(positions) != 18:
        raise ExternalParseError(
            "RDAHELPER requires 18 pipe-delimited positions",
            failure_code="invalid_rda_position_count",
            failing_column=1,
        )

    flags = []
    for position in RDA_SWITCH_POSITIONS:
        switch = positions[position - 1]
        if switch not in {"0", "1"}:
            raise ExternalParseError(
                f"RDAHELPER position {position} must be 0 or 1",
                failure_code="invalid_rda_switch",
                failing_column=1,
                failing_position=position,
            )
        flags.append(switch == "1")
    return tuple(flags)


def _decode_boolean_flags(
    values: tuple[str, ...],
    *,
    label: str,
    first_column: int,
) -> tuple[bool, ...]:
    return tuple(
        _require_boolean(
            value,
            label=f"{label} flag {index}",
            column=first_column + index - 1,
        )
        for index, value in enumerate(values, start=1)
    )


def _decode_options(
    verb: str, arguments: tuple[str, ...]
) -> tuple[int | None, tuple[bool, ...]]:
    if verb == "ADD":
        return _require_integer(
            arguments[2],
            label="ADD option",
            accepted={100, 101, 106, 108},
            column=3,
        ), ()
    if verb == "COPY":
        return None, (
            _require_boolean(arguments[2], label="COPY flag 1", column=3),
            _require_boolean(arguments[5], label="COPY flag 2", column=6),
        )
    if verb == "DELETE":
        return (
            _require_integer(
                arguments[2], label="DELETE option", accepted={0}, column=3
            ),
            _decode_boolean_flags(
                arguments[3:8], label="DELETE", first_column=4
            ),
        )
    if verb == "EDITFIELD":
        return _require_integer(
            arguments[2], label="EDITFIELD option", accepted={0}, column=3
        ), ()
    if verb == "RDAHELPER":
        return None, _decode_rda_flags(arguments[0])
    if verb == "REPLACE":
        option_code = _require_integer(
            arguments[2],
            label="REPLACE option 1",
            accepted={0, 2},
            column=3,
        )
        _require_integer(
            arguments[4],
            label="REPLACE option 2",
            accepted={0, 1, 2},
            column=5,
        )
        flags = (
            (
                _require_boolean(
                    arguments[5], label="REPLACE flag 1", column=6
                ),
            )
            if len(arguments) >= 6
            else ()
        )
        return option_code, flags
    if verb == "SORTBY":
        return None, _decode_boolean_flags(
            arguments[1:3], label="SORTBY", first_column=2
        )
    if verb == "SUBFIELD_EDIT":
        return _pipe_option(
            arguments[4],
            label="SUBFIELD_EDIT option",
            accepted={0, 101},
            column=5,
        ), ()
    if verb == "SUBFIELD_REMOVE":
        return _pipe_option(
            arguments[3],
            label="SUBFIELD_REMOVE option",
            accepted={107},
            column=4,
        ), ()
    if verb == "buildnewfield":
        return None, _decode_boolean_flags(
            arguments[1:5], label="Build Field", first_column=2
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
    verb = parts[0].strip() if parts else ""
    arguments = tuple(parts[1:])
    instruction_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    try:
        if not verb:
            raise ExternalParseError(
                "instruction verb is required",
                failure_code="verb_required",
                failing_column=0,
            )
        if verb not in _ARGUMENT_COUNTS:
            raise ExternalParseError(
                f"unsupported instruction verb {verb!r}",
                failure_code="unsupported_verb",
                failing_column=0,
            )

        minimum, maximum = _ARGUMENT_COUNTS[verb]
        if len(arguments) < minimum:
            raise ExternalParseError(
                f"{verb} requires at least {minimum} argument columns; "
                f"got {len(arguments)}",
                failure_code="missing_columns",
                failing_column=len(arguments) + 1,
            )
        for index, value in enumerate(
            arguments[maximum:], start=maximum + 1
        ):
            if value:
                raise ExternalParseError(
                    f"{verb} has nonempty surplus column {index}",
                    failure_code="surplus_column",
                    failing_column=index,
                )

        option_code, boolean_flags = _decode_options(
            verb, arguments[:maximum]
        )
    except ExternalParseError as exc:
        raise exc.with_context(
            source_line=normalized,
            source_entry=source_entry,
            line_number=line_number,
            instruction_sha256=instruction_sha256,
            verb=verb,
            arguments=arguments,
        ) from None

    return ExternalInstruction(
        verb=verb,
        arguments=arguments,
        source_line=normalized,
        source_entry=source_entry,
        line_number=line_number,
        instruction_sha256=instruction_sha256,
        option_code=option_code,
        boolean_flags=boolean_flags,
    )


def instruction_shape(value: ExternalInstruction) -> str:
    """Return a value-neutral compatibility shape identifier."""
    if (
        value.verb == "COPY"
        and value.boolean_flags == (False, False)
        and not value.arguments[4]
        and not value.arguments[6]
    ):
        if re.fullmatch(r"\$[a-z0-9].+", value.arguments[3]):
            return "copy-filter-subfield"
        if not value.arguments[3]:
            return "copy-unfiltered"
    if value.verb == "SUBFIELD_EDIT":
        find = value.arguments[2]
        replacement = value.arguments[3]
        if value.option_code == 101 and not find:
            return "subfield-edit-add-if-missing"
        if value.option_code == 0 and "|" not in replacement:
            if find == "^b":
                return "subfield-edit-prepend"
            if find == "^e":
                return "subfield-edit-append"
    if (
        value.verb == "SUBFIELD_EDIT"
        and value.option_code == 0
        and value.arguments[2]
        and not value.arguments[2].startswith("^")
        and "|" not in value.arguments[3]
    ):
        return "subfield-edit-literal"
    if value.verb == "SUBFIELD_REMOVE" and value.option_code == 107:
        return "subfield-remove-exact"
    if value.verb == "DELETE" and not value.arguments[1] and not any(
        value.boolean_flags
    ):
        return (
            "delete-wildcard"
            if "X" in value.arguments[0].upper()
            else "delete-exact"
        )
    if (
        value.verb == "DELETE"
        and value.arguments[1]
        and not any(value.boolean_flags)
        and "$" not in value.arguments[1]
        and "\\" not in value.arguments[1]
    ):
        return "delete-subfield-text"
    if (
        value.verb == "DELETE"
        and value.arguments[0] == "650"
        and value.arguments[1] == r"\6$a"
        and value.boolean_flags == (False, False, False, False, False)
    ):
        return "delete-mnemonic-exists"
    if value.verb == "DELETE" and is_characterized_delete_mnemonic_regex(
        value.arguments[0], value.arguments[1], value.boolean_flags
    ):
        return "delete-mnemonic-regex"
    if value.verb == "ADD" and not value.arguments[3]:
        return {
            100: "add-append",
            101: "add-skip-tag",
            108: "add-skip-identical",
        }.get(value.option_code, "add-unrecognized")
    if value.verb == "ADD" and value.option_code == 106:
        return "add-leader"
    if value.verb == "buildnewfield":
        return {
            (False, False, True, False): "build-if-absent",
            (False, False, False, True): "build-always",
        }.get(value.boolean_flags, "buildnewfield-unrecognized")
    if value.verb == "RDAHELPER" and value.arguments[0] == (
        "1|1|0|0|0|0|0|0|0|0|0|0|0|0|0|0|language of cataloging|0"
    ):
        return "rda-smith-classify"
    if (
        value.verb == "SORTBY"
        and value.arguments[0] == "ALL"
        and value.boolean_flags == (True, True)
    ):
        return "sort-all"
    if value.verb == "REPLACE":
        shape = characterized_replace_shape(value.instruction_sha256)
        if shape is not None:
            return shape
    return f"{value.verb.replace('_', '-').lower()}-unrecognized"
