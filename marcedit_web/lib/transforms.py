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


# --- 003/001 introspection ---------------------------------------------------


def control_value(record: Record, tag: str) -> str | None:
    """Return the data of a control field (e.g. '001', '003') or None."""
    field = record.get(tag)
    if field is None:
        return None
    return field.data


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
