"""Parser for the extended ``marc-rules.txt`` format.

The file is a single source of truth for both structural validation rules
and click-through tooltip help. The existing MARC21 rule-line format is
preserved; three additive directives carry the new help payload:

1. **Field-level help** via ``####`` continuation on the field-heading line::

       245    1   ...   ####Specifies the Primary Title...

2. **``:help`` continuation lines** that attach to the most recently seen
   rule (field, indicator, length, subfield, or byte position)::

       a   NR   International Standard Book Number
       :help   The actual ISBN. Hyphens optional.

   Multiple ``:help`` lines stack as paragraphs separated by ``\\n\\n``.

3. **``:byte`` lines** declaring byte positions on control fields
   (LDR/006/007/008)::

       008    NR   FIXED-LENGTH DATA ELEMENTS...
       length 40
       :byte  0-5     Date entered on file (YYMMDD)
       :byte  28      Government publication code
       :help  Codes: 'i' = international intergovernmental, ...

Backward compatibility: any line whose first column is not one of the
known directives is reported as a :class:`RulesParseWarning` but does
not abort the load. The parser never raises on bad input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


Repeatability = Literal["R", "NR"]


@dataclass
class IndicatorRule:
    codes: str          # raw codes column, e.g. "blank", "b7", "01", "0-9"
    label: str
    help_text: str = ""

    def allowed_chars(self) -> set[str]:
        """Expand ``codes`` to the set of characters allowed in the indicator.

        Conventions in the source file:
          * ``"blank"`` → only the space character.
          * ``"b<X>"`` → space plus each character in ``X`` (e.g. ``"b7"``
            → ``{" ", "7"}``).
          * ``"0-9"`` → all digits.
          * ``"01"`` → ``{"0", "1"}`` (each char allowed).
        """
        codes = self.codes.strip()
        if not codes or codes.lower() == "blank":
            return {" "}
        out: set[str] = set()
        # `b` prefix is "blank or these".
        if codes[0] == "b":
            out.add(" ")
            codes = codes[1:]
        # Range form: "0-9" or "a-z".
        if len(codes) == 3 and codes[1] == "-":
            lo, hi = codes[0], codes[2]
            out.update(chr(c) for c in range(ord(lo), ord(hi) + 1))
            return out
        # Otherwise each character is its own allowed value.
        out.update(codes)
        return out


@dataclass
class SubfieldRule:
    code: str
    repeatability: Repeatability
    label: str
    help_text: str = ""


@dataclass
class LengthRule:
    """Length spec from the ``length <spec>`` line in the rules file.

    ``spec`` is preserved verbatim. ``exact`` is set when the spec is a
    simple integer (e.g. ``"40"`` for 008). The variant-by-first-byte
    syntax used for 007 (``"a:8,c:6|14,..."``) is kept in ``variants``
    as ``{first_byte: list[int]}`` but treated as advisory for v1 — the
    validator only enforces the exact length when ``exact`` is set.
    """

    spec: str
    exact: int | None = None
    variants: dict[str, list[int]] = field(default_factory=dict)
    help_text: str = ""


@dataclass
class BytePos:
    start: int          # 0-based, inclusive
    end: int            # 0-based, inclusive
    label: str
    help_text: str = ""


@dataclass
class FieldRule:
    tag: str
    repeatability: Repeatability
    heading: str
    help_text: str = ""
    ind1: IndicatorRule | None = None
    ind2: IndicatorRule | None = None
    valid_subfield_codes: str = ""          # the `subfield abcdef68` summary
    length: LengthRule | None = None
    subfields: dict[str, SubfieldRule] = field(default_factory=dict)
    byte_positions: list[BytePos] = field(default_factory=list)


@dataclass
class CrossRecordRules:
    only_one_1xx: bool = False
    must_have_245: bool = False
    dedup_keys: list[str] = field(default_factory=list)


@dataclass
class RuleSet:
    fields: dict[str, FieldRule] = field(default_factory=dict)
    cross_record: CrossRecordRules = field(default_factory=CrossRecordRules)


@dataclass
class RulesParseWarning:
    line_no: int
    line: str
    message: str


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


_FIELD_DIRECTIVES = {"ind1", "ind2", "subfield", "length"}
_CONTINUATION_DIRECTIVES = {":help", ":byte"}
_HEADER_DIRECTIVES = {"1xx", "245", "dedup"}


def parse_rules(path: Path) -> tuple[RuleSet, list[RulesParseWarning]]:
    """Parse ``path`` into a :class:`RuleSet` plus any non-fatal warnings.

    Never raises on bad input; everything anomalous is in the returned
    warning list. An empty file yields an empty RuleSet.
    """
    return parse_rules_text(path.read_text())


def parse_rules_text(text: str) -> tuple[RuleSet, list[RulesParseWarning]]:
    """Parse ``text`` (in-memory variant of :func:`parse_rules`)."""
    rules = RuleSet()
    warnings: list[RulesParseWarning] = []

    current_field: FieldRule | None = None
    # The most recently attached rule object — `:help` lines attach here.
    attach_target: object | None = None

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()

        # Comment / blank handling -------------------------------------------------
        stripped = line.lstrip()
        if not stripped:
            # Blank line closes any open field block.
            current_field = None
            attach_target = None
            continue
        if stripped.startswith("#") and not stripped.startswith("####"):
            # Line-level comment in the source (e.g. "# Uncomment these lines").
            # `####` is reserved as the field-help continuation; that's only
            # legal as a trailing column on the heading line, not as a
            # standalone comment, so a bare `####` line falls through to
            # the unknown-directive branch.
            continue

        cols = line.split("\t")
        # Trim trailing empty cols (the source file sometimes has them).
        while cols and cols[-1] == "":
            cols.pop()
        if not cols:
            current_field = None
            attach_target = None
            continue

        first = cols[0]

        # ---- Continuation lines (:help / :byte) ---------------------------------
        if first == ":help":
            if attach_target is None:
                warnings.append(RulesParseWarning(
                    line_no, line,
                    ":help has no preceding rule to attach to; ignored",
                ))
                continue
            payload = "\t".join(cols[1:]).strip()
            _append_help(attach_target, payload)
            continue

        if first == ":byte":
            if current_field is None:
                warnings.append(RulesParseWarning(
                    line_no, line,
                    ":byte is only valid inside a field block; ignored",
                ))
                continue
            byte_pos, parse_err = _parse_byte_line(cols)
            if parse_err is not None:
                warnings.append(RulesParseWarning(line_no, line, parse_err))
                continue
            current_field.byte_positions.append(byte_pos)
            attach_target = byte_pos
            continue

        # ---- File-scope directives (only valid outside a field block) -----------
        if first == "dedup":
            keys = cols[1].split(",") if len(cols) > 1 else []
            rules.cross_record.dedup_keys = [k.strip() for k in keys if k.strip()]
            current_field = None
            attach_target = None
            continue

        # ---- Tag-shaped first column (3 alnum or "LDR") -------------------------
        # The same first column can be either a cross-record header rule
        # (e.g. `245   1   One 245 must be present`) or a real field-block
        # opener (e.g. `245   NR   TITLE STATEMENT`). We dispatch on column 2:
        # `R` or `NR` → field block, anything else → cross-record/header rule.
        if _looks_like_tag_opener(first):
            second = cols[1].strip() if len(cols) > 1 else ""
            if second.upper() in {"R", "NR"}:
                # Field-block opener.
                if len(cols) < 3:
                    warnings.append(RulesParseWarning(
                        line_no, line,
                        f"field block for {first!r} is missing the heading column",
                    ))
                    continue
                tag = first
                heading = cols[2].strip()
                help_text = ""
                if len(cols) > 3:
                    trailing = cols[3]
                    if trailing.startswith("####"):
                        help_text = trailing[4:].strip()
                current_field = FieldRule(
                    tag=tag,
                    repeatability=second.upper(),  # type: ignore[arg-type]
                    heading=heading,
                    help_text=help_text,
                )
                rules.fields[tag] = current_field
                attach_target = current_field
                continue
            # Cross-record / header rule.
            current_field = None
            attach_target = None
            if first.lower() == "1xx":
                rules.cross_record.only_one_1xx = True
            elif first == "245":
                rules.cross_record.must_have_245 = True
            else:
                warnings.append(RulesParseWarning(
                    line_no, line,
                    f"unknown header-style rule {first!r}; "
                    f"column 2 is {second!r}, expected R, NR, or a known constraint",
                ))
            continue

        # ---- Inside a field block ----------------------------------------------
        if current_field is None:
            warnings.append(RulesParseWarning(
                line_no, line,
                f"unknown directive {first!r} outside any field block; ignored",
            ))
            continue

        if first == "length":
            spec = cols[1].strip() if len(cols) > 1 else ""
            current_field.length = _parse_length_rule(spec)
            attach_target = current_field.length
            continue

        if first in ("ind1", "ind2"):
            codes = cols[1].strip() if len(cols) > 1 else "blank"
            label = cols[2].strip() if len(cols) > 2 else ""
            rule = IndicatorRule(codes=codes, label=label)
            if first == "ind1":
                current_field.ind1 = rule
            else:
                current_field.ind2 = rule
            attach_target = rule
            continue

        if first == "subfield":
            current_field.valid_subfield_codes = (
                cols[1].strip() if len(cols) > 1 else ""
            )
            # The summary line itself isn't a help-attachable rule; the
            # per-subfield rules below are.
            attach_target = None
            continue

        if first == "":
            # Empty first column means "the default subfield rule for control
            # fields" — captured for parity but unused by validate_records.
            attach_target = None
            continue

        # Single-character (or digit) subfield code, e.g. `a`, `b`, `2`, `8`.
        if len(first) == 1 and (first.isalpha() or first.isdigit()):
            if len(cols) < 2:
                warnings.append(RulesParseWarning(
                    line_no, line,
                    f"subfield rule {first!r} missing repeatability column",
                ))
                continue
            rep = cols[1].strip().upper()
            if rep not in {"R", "NR"}:
                warnings.append(RulesParseWarning(
                    line_no, line,
                    f"subfield {first!r}: repeatability column {cols[1]!r} "
                    "is not R or NR; treating as R",
                ))
                rep = "R"
            label = cols[2].strip() if len(cols) > 2 else ""
            sf_rule = SubfieldRule(
                code=first,
                repeatability=rep,  # type: ignore[arg-type]
                label=label,
            )
            current_field.subfields[first] = sf_rule
            attach_target = sf_rule
            continue

        warnings.append(RulesParseWarning(
            line_no, line,
            f"unknown directive {first!r} inside field block "
            f"{current_field.tag!r}; ignored",
        ))

    return rules, warnings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _looks_like_tag_opener(token: str) -> bool:
    if token == "LDR":
        return True
    if len(token) != 3:
        return False
    # MARC tags are 3 chars, normally 3 digits, but the source file also
    # uses placeholders like ``0XX`` if any are ever introduced. Accept
    # alphanumerics; the parser doesn't need to validate tag legality
    # itself — that's the rules' job.
    return all(c.isalnum() for c in token)


def _parse_length_rule(spec: str) -> LengthRule:
    rule = LengthRule(spec=spec)
    if not spec:
        return rule
    if spec.isdigit():
        rule.exact = int(spec)
        return rule
    # Variant form, e.g. "a:8,c:6|14,d:6,...". Best-effort parse; bad
    # entries are silently skipped — validator treats unparseable variants
    # as "advisory only".
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        key, vals = entry.split(":", 1)
        key = key.strip()
        lengths: list[int] = []
        for v in vals.split("|"):
            v = v.strip()
            if v.isdigit():
                lengths.append(int(v))
        if key and lengths:
            rule.variants[key] = lengths
    return rule


def _parse_byte_line(cols: list[str]) -> tuple[BytePos, str | None]:
    """Parse a ``:byte`` row into a BytePos. Returns (pos, error_or_None)."""
    if len(cols) < 3:
        return BytePos(0, 0, ""), (
            ":byte requires a position (or range) and a label"
        )
    range_token = cols[1].strip()
    label = cols[2].strip()
    if "-" in range_token:
        lo_s, hi_s = range_token.split("-", 1)
        try:
            lo, hi = int(lo_s), int(hi_s)
        except ValueError:
            return BytePos(0, 0, ""), (
                f":byte range {range_token!r} is not numeric"
            )
        if lo > hi:
            return BytePos(0, 0, ""), (
                f":byte range {range_token!r} has lo > hi"
            )
    else:
        try:
            lo = hi = int(range_token)
        except ValueError:
            return BytePos(0, 0, ""), (
                f":byte position {range_token!r} is not numeric"
            )
    return BytePos(start=lo, end=hi, label=label), None


def _append_help(target: object, text: str) -> None:
    """Append ``text`` to ``target.help_text``, stacking as paragraphs."""
    if not text:
        return
    existing = getattr(target, "help_text", "")
    if existing:
        setattr(target, "help_text", existing + "\n\n" + text)
    else:
        setattr(target, "help_text", text)
