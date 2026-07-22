"""Low-level MARC record transforms.

Each function here mirrors one or more lines in MarcEdit's task language.
Functions take a `pymarc.Record`, mutate it in place, and return None unless
otherwise noted.

Leader-based conditionals replicate the regex anchors MarcEdit uses against
the `.mrk` representation. For example, MarcEdit's
`=LDR.{8}[a,c,d,i,j,m,o,p,r,t][c,m,s,i]` resolves to:
    leader[6] in {a,c,d,i,j,m,o,p,r,t} AND leader[7] in {c,m,s,i}
because `=LDR` (4 chars) + 2 spaces = offset 6 into the line, and MARC leader
positions 6 and 7 are record type and bibliographic level respectively.
"""

from __future__ import annotations

import re

from pymarc import Field, Record, Subfield


# --- Leader/008 helpers ------------------------------------------------------


def leader_type(record: Record) -> str:
    """Return MARC leader byte 06 (record type)."""
    return record.leader[6]


def leader_biblevel(record: Record) -> str:
    """Return MARC leader byte 07 (bibliographic level)."""
    return record.leader[7]


def set_008_form_of_item(record: Record, form: str = "o") -> None:
    """Set the 008 form-of-item position to `form` based on leader.

    For record types {a,c,d,i,j,m,o,p,r,t} with bib levels {c,m,s,i} the
    target is 008 byte 23. For record types {e,f,g,k} (maps, visual materials)
    the target is 008 byte 29.
    """
    field_008 = record.get("008")
    if field_008 is None:
        return

    rtype = leader_type(record)
    blevel = leader_biblevel(record)
    data = field_008.data

    if rtype in "acdijmoprt" and blevel in "cmsi":
        position = 23
    elif rtype in "efgk":
        position = 29
    else:
        return

    if len(data) > position:
        field_008.data = data[:position] + form + data[position + 1 :]


# --- Field delete / replace --------------------------------------------------


def delete_tags(record: Record, *tags: str) -> None:
    """Delete every field matching any of the given tags.

    Tags can be exact ('029') or 3-char prefixes via the 'X' wildcard
    ('9XX' means tags 900-999). Mirrors MarcEdit `DELETE <tag>` lines.
    """
    expanded: set[str] = set()
    for tag in tags:
        if "X" not in tag and "x" not in tag:
            expanded.add(tag)
            continue
        # Expand wildcards (e.g. 9XX -> 900..999)
        ranges = [range(10) if c.lower() == "x" else [int(c)] for c in tag]
        for d0 in ranges[0]:
            for d1 in ranges[1]:
                for d2 in ranges[2]:
                    expanded.add(f"{d0}{d1}{d2}")

    record.remove_fields(*expanded)


def delete_fields_matching_subfield(
    record: Record, tag: str, subfield_code: str, contains: str
) -> None:
    """Delete fields with `tag` whose `subfield_code` contains `contains`.

    Used for targeted deletions like "remove 655 fields mentioning Electronic
    books" before re-adding a canonical form.
    """
    needle = contains.lower()
    keep = []
    for field in record.get_fields(tag):
        values = " ".join(field.get_subfields(subfield_code)).lower()
        if needle not in values:
            keep.append(field)
    record.remove_fields(tag)
    for field in keep:
        record.add_ordered_field(field)


def delete_856_fields_matching_url(record: Record, contains: str) -> None:
    """Delete 856 fields whose $u contains the given text.

    This is narrower than `delete_fields_matching_subfield`: it only inspects
    URL subfields, so labels or notes that happen to mention the same vendor
    text do not cause the access field to be removed.
    """
    needle = contains.lower().strip()
    if not needle:
        return

    keep = []
    for field in record.get_fields("856"):
        urls = field.get_subfields("u")
        if any(needle in url.lower() for url in urls):
            continue
        keep.append(field)
    record.remove_fields("856")
    for field in keep:
        record.add_ordered_field(field)


def delete_856_fields_matching_url_regex(
    record: Record, pattern: str, *, ignore_case: bool = True
) -> None:
    """Delete 856 fields whose $u matches the given regular expression.

    Uses `re.search`, so the pattern need not anchor — `^…$` to require a full
    match. Compile-time errors raise `re.error` so the cataloger sees the
    failure before any records are mutated.
    """
    if not pattern:
        return
    flags = re.IGNORECASE if ignore_case else 0
    compiled = re.compile(pattern, flags)

    keep = []
    for field in record.get_fields("856"):
        urls = field.get_subfields("u")
        if any(compiled.search(url) for url in urls):
            continue
        keep.append(field)
    record.remove_fields("856")
    for field in keep:
        record.add_ordered_field(field)


# --- Field construction ------------------------------------------------------


def make_field(tag: str, ind1: str, ind2: str, *subfields: tuple[str, str]) -> Field:
    """Build a pymarc.Field from indicators and (code, value) pairs.

    `ind1` and `ind2` accept a single character; pass `'\\'` (backslash) or
    `' '` for a blank indicator to mirror MarcEdit's `\\` / `\\\\` notation.
    """

    def normalize(ind: str) -> str:
        if ind in ("", "\\", "\\\\"):
            return " "
        return ind

    return Field(
        tag=tag,
        indicators=[normalize(ind1), normalize(ind2)],
        subfields=[Subfield(code=c, value=v) for c, v in subfields],
    )


def add_field_if_absent(record: Record, field: Field) -> bool:
    """Append `field` only if no field with the same tag already matches.

    "Matches" means identical indicators and identical subfields. Returns
    True if added.
    """
    new_sig = (
        tuple(field.indicators),
        tuple((sf.code, sf.value) for sf in field.subfields),
    )
    for existing in record.get_fields(field.tag):
        sig = (
            tuple(existing.indicators),
            tuple((sf.code, sf.value) for sf in existing.subfields),
        )
        if sig == new_sig:
            return False
    record.add_ordered_field(field)
    return True


# --- Field sort --------------------------------------------------------------


def sort_fields(record: Record) -> None:
    """Sort variable fields by tag (preserving relative order within a tag)."""
    record.fields.sort(key=lambda f: f.tag)


def is_control_tag(tag: str) -> bool:
    """True for control-field tags 001-009 (no indicators, no subfields).

    Excludes the leader sentinel "000". Shared by rules_validate and
    mrk_parser (TASK-078c)."""
    return (
        len(tag) == 3
        and tag.startswith("00")
        and tag[2].isdigit()
        and tag != "000"
    )


# --- 003/001 introspection ---------------------------------------------------


def control_value(record: Record, tag: str) -> str | None:
    """Return the data of a control field (e.g. '001', '003') or None."""
    field = record.get(tag)
    if field is None:
        return None
    return field.data


def normalize_oclc_035(value: str) -> str | None:
    """Return the bare OCLC number from one 035 $a value, or None.

    `value` is a single 035 $a. Returns the identifier with the ``(OCoLC)``
    prefix removed (``"(OCoLC)12345"`` -> ``"12345"``,
    ``"(OCoLC)ocm00012345"`` -> ``"ocm00012345"``). Returns None when the
    value lacks the ``(OCoLC)`` prefix (bare numbers included) or is empty
    after stripping. Leading whitespace is tolerated; the result is
    whitespace-stripped. The ocm/ocn/on prefix and leading zeros are kept
    verbatim.

    This is the single owner of OCLC-035 extraction semantics (TASK-078a) —
    a generic primitive shared by preflight, reporting, and marc_diff;
    distinct from the removed Smith-specific canonicalizer.
    """
    prefix = "(OCoLC)"
    stripped = (value or "").lstrip()
    if not stripped.startswith(prefix):
        return None
    return stripped[len(prefix):].strip() or None


# --- TASK-030: Task Builder ops expansion ------------------------------------
#
# Helpers added in lockstep with new entries in
# ``task_builder.OPERATIONS_PALETTE``. Each is a pure
# ``(record, ...) -> None`` mutation; the form-builder emits a call
# to one of these via ``codegen_safety.lit`` for every user-supplied
# value, so a malicious tag/value can't escape its string literal.


def copy_field(record: Record, src_tag: str, dst_tag: str) -> None:
    """Duplicate every ``src_tag`` field as a new ``dst_tag`` field.

    Same indicators + same subfields. The original ``src_tag`` field
    stays; use :func:`move_field` to re-tag in place.
    """
    if not src_tag or not dst_tag:
        return
    sources = list(record.get_fields(src_tag))
    for field in sources:
        if field.is_control_field():
            # Control fields have ``.data`` instead of indicators +
            # subfields. Copy that shape.
            record.add_ordered_field(Field(tag=dst_tag, data=field.data))
            continue
        record.add_ordered_field(Field(
            tag=dst_tag,
            indicators=list(field.indicators),
            subfields=[Subfield(code=sf.code, value=sf.value)
                       for sf in field.subfields],
        ))


def move_field(record: Record, src_tag: str, dst_tag: str) -> None:
    """Re-tag every ``src_tag`` field as ``dst_tag``.

    Equivalent to :func:`copy_field` followed by ``record.remove_fields(src_tag)``.
    """
    if not src_tag or not dst_tag or src_tag == dst_tag:
        return
    copy_field(record, src_tag, dst_tag)
    record.remove_fields(src_tag)


def add_subfield_to_fields(
    record: Record,
    tag: str,
    code: str,
    value: str,
    *,
    position: str = "end",
) -> None:
    """Append (or prepend) a subfield to every variable field with ``tag``.

    ``position`` is ``"end"`` (default) or ``"start"``. Control fields
    don't have subfields and are skipped silently.
    """
    if not tag or not code:
        return
    for field in record.get_fields(tag):
        if field.is_control_field():
            continue
        new_sf = Subfield(code=code, value=value)
        if position == "start":
            field.subfields.insert(0, new_sf)
        else:
            field.subfields.append(new_sf)


def delete_subfields(record: Record, tag: str, *codes: str) -> None:
    """Remove subfields with any of the listed codes from every ``tag`` field.

    Control fields have no subfields and are skipped silently. Empty
    code list is a no-op.
    """
    if not tag or not codes:
        return
    drop = {c for c in codes if c}
    for field in record.get_fields(tag):
        if field.is_control_field():
            continue
        field.subfields = [sf for sf in field.subfields if sf.code not in drop]


def delete_subfields_matching_value(
    record: Record,
    tag: str,
    code: str,
    value: str,
    *,
    match: str = "exact",
    trim: bool = True,
    ignore_case: bool = False,
) -> None:
    """Remove subfields whose value matches the requested comparison."""
    if not tag or not code:
        return

    flags = re.IGNORECASE if ignore_case else 0
    pattern = re.compile(value, flags) if match == "regex" else None
    expected = value.lower() if ignore_case and match != "regex" else value

    def comparison_text(raw: str) -> str:
        text = raw.strip() if trim else raw
        return text.lower() if ignore_case and match != "regex" else text

    def should_delete(raw: str) -> bool:
        text = comparison_text(raw)
        if match == "contains":
            return expected in text
        if match == "regex":
            return pattern.search(text) is not None
        return text == expected

    for field in record.get_fields(tag):
        if field.is_control_field():
            continue
        field.subfields = [
            sf
            for sf in field.subfields
            if sf.code != code or not should_delete(sf.value)
        ]


def copy_subfield_within_field(
    record: Record, tag: str, src_code: str, dst_code: str
) -> None:
    """Within each ``tag`` field, append ``$dst_code`` for every existing
    ``$src_code``, carrying the value over.

    Useful for invalidating-in-place patterns ($a → $z on ISBN, for
    example): copy the value, then a separate ``delete-subfield`` op
    drops the original.
    """
    if not tag or not src_code or not dst_code:
        return
    for field in record.get_fields(tag):
        if field.is_control_field():
            continue
        # Snapshot first so we don't iterate the list we're appending to.
        sources = [sf for sf in field.subfields if sf.code == src_code]
        for sf in sources:
            field.subfields.append(Subfield(code=dst_code, value=sf.value))


def set_indicators(
    record: Record,
    tag: str,
    *,
    ind1: str | None = None,
    ind2: str | None = None,
) -> None:
    """Override one or both indicators on every variable field with ``tag``.

    ``None`` leaves the existing indicator alone. Pass a space (``" "``)
    to set blank. Control fields have no indicators and are skipped.

    Note: pymarc 5's :class:`Field.indicators` is an immutable
    :class:`Indicators` tuple, so we reconstruct the pair and assign it
    wholesale rather than indexing in.
    """
    if not tag or (ind1 is None and ind2 is None):
        return
    for field in record.get_fields(tag):
        if field.is_control_field():
            continue
        existing = list(field.indicators)
        new_ind1 = existing[0] if ind1 is None else ind1
        new_ind2 = existing[1] if ind2 is None else ind2
        field.indicators = [new_ind1, new_ind2]


def replace_field_subfield_and_indicators(
    record: Record,
    tag: str,
    match_ind1: str,
    match_ind2: str,
    match_code: str,
    match_value: str,
    new_ind1: str,
    new_ind2: str,
    new_code: str,
    new_value: str,
    *,
    regex: bool = False,
    ignore_case: bool = False,
) -> None:
    """Update indicators and matching subfield text on matched fields."""

    def normalize_indicator(value: str) -> str:
        if value in ("", "\\", "\\\\"):
            return " "
        return value[:1]

    if not tag or not match_code or not new_code:
        return

    flags = re.IGNORECASE if ignore_case else 0
    pattern = re.compile(match_value, flags) if regex else None
    if pattern is not None:
        pattern.sub(new_value, "")

    expected_indicators = [
        normalize_indicator(match_ind1),
        normalize_indicator(match_ind2),
    ]
    replacement_indicators = [
        normalize_indicator(new_ind1),
        normalize_indicator(new_ind2),
    ]
    for field in record.get_fields(tag):
        if field.is_control_field():
            continue
        if list(field.indicators) != expected_indicators:
            continue
        updated = False
        subfields = []
        for subfield in field.subfields:
            if subfield.code != match_code:
                subfields.append(subfield)
                continue

            if pattern is not None:
                value, replacements = pattern.subn(new_value, subfield.value)
                if replacements == 0:
                    subfields.append(subfield)
                    continue
            else:
                if subfield.value != match_value:
                    subfields.append(subfield)
                    continue
                value = new_value

            subfields.append(Subfield(code=new_code, value=value))
            updated = True
        if updated:
            field.indicators = replacement_indicators
            field.subfields = subfields


def regex_replace_field_data(
    record: Record,
    tag: str,
    pattern: str,
    replacement: str,
    *,
    ignore_case: bool = False,
) -> None:
    """Apply ``re.sub(pattern, replacement, …)`` across every ``tag`` field.

    Control fields edit ``.data``; variable fields rebuild each
    subfield with the replaced value (pymarc 5's :class:`Subfield` is
    a frozen NamedTuple, so we reconstruct the list rather than
    mutating in place). Compile errors raise ``re.error`` before any
    field is mutated.
    """
    if not tag or not pattern:
        return
    flags = re.IGNORECASE if ignore_case else 0
    compiled = re.compile(pattern, flags)
    for field in record.get_fields(tag):
        if field.is_control_field():
            field.data = compiled.sub(replacement, field.data)
            continue
        field.subfields = [
            Subfield(code=sf.code, value=compiled.sub(replacement, sf.value))
            for sf in field.subfields
        ]


# --- 035 dedup (generic; non-OCLC-specific) ----------------------------------


def dedupe_035(record: Record) -> None:
    """Remove duplicate 035 fields, keeping the first occurrence.

    Dedup key is `(ind1, ind2, tuple_of_(code, value))` — full subfield
    equality, not just `$a`. This is conservative: differing qualifiers
    or alternate subfields keep both fields.
    """
    seen: set[tuple] = set()
    keep: list[Field] = []
    for field in record.get_fields("035"):
        key = (
            field.indicators[0],
            field.indicators[1],
            tuple((sf.code, sf.value) for sf in field.subfields),
        )
        if key in seen:
            continue
        seen.add(key)
        keep.append(field)
    record.remove_fields("035")
    for field in keep:
        record.add_ordered_field(field)
