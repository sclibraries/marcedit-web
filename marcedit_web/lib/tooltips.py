"""Small Streamlit-side renderers for :class:`HelpEntry` payloads.

Kept separate from :mod:`help_lookup` so the resolver stays
Streamlit-free and unit-testable. This module is imported only by
the View page (Stage 7) and, later, by the MarcEditor's Ace
integration (Stage 11, v1.5).
"""

from __future__ import annotations

from typing import Iterable

from .help_lookup import HelpEntry


_NO_ENTRY_MARKDOWN = (
    "_No help entry yet for this selection._  \n"
    "Tag, subfield, or byte position not found in `data/marc-rules.txt`. "
    "Adding a `:help` or `:byte` directive under the field block will make "
    "the help appear here on the next page load."
)


def render_help_entry(entry: HelpEntry | None) -> str:
    """Return a markdown blob suitable for `st.markdown(...)`."""
    if entry is None:
        return _NO_ENTRY_MARKDOWN
    return (
        f"**{entry.title}**\n\n"
        f"{entry.body}\n\n"
        f"<sub>{entry.source}</sub>"
    )


def variable_field_subfield_codes(
    field, valid_codes: str
) -> Iterable[str]:
    """Subfield codes actually present on `field`, in record order,
    then any rule-declared codes the field doesn't currently carry.

    Used by the View page to populate a subfield-code selector with the
    most-relevant codes first.
    """
    present = []
    seen: set[str] = set()
    for sf in field.subfields:
        if sf.code not in seen:
            present.append(sf.code)
            seen.add(sf.code)
    extras = [c for c in valid_codes if c not in seen]
    return present + extras
