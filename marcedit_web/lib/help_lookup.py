"""Help lookup over a parsed :class:`RuleSet`.

Resolves a tag / subfield / byte-position request to a single
:class:`HelpEntry`, drawn directly from the extended ``marc-rules.txt``.
The View page (Stage 7) and the eventual in-Ace tooltips (Stage 11, v1.5)
both consume this surface.

Resolution order:

1. If ``byte`` is supplied, look up a matching :class:`BytePos` on the
   field rule. Returns ``None`` if no byte-position entry covers it.
2. Else if ``subfield`` is supplied, look up that code in the field
   rule's ``subfields`` dict. Returns ``None`` if not registered.
3. Else fall back to the field-level entry (heading + ``####`` help).

Returns ``None`` (never raises) for any missing rule. The Streamlit page
surfaces ``None`` as a friendly "no entry yet" message rather than an
error so the cataloger knows to add the directive to the rules file.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rules import FieldRule, RuleSet


@dataclass(frozen=True)
class HelpEntry:
    """One resolved help payload, ready for rendering."""

    title: str
    body: str           # plain text or simple markdown
    source: str         # human-readable provenance, e.g. "marc-rules.txt :byte 008"


def help_for(
    rules: RuleSet,
    *,
    tag: str,
    subfield: str | None = None,
    byte: int | None = None,
) -> HelpEntry | None:
    """Resolve a single help entry, or ``None`` if nothing applies."""
    if not tag:
        return None
    field_rule = rules.fields.get(tag)
    if field_rule is None:
        return None

    if byte is not None:
        return _byte_help(field_rule, byte)
    if subfield is not None and subfield != "":
        return _subfield_help(field_rule, subfield)
    return _field_help(field_rule)


def _byte_help(rule: FieldRule, position: int) -> HelpEntry | None:
    for bp in rule.byte_positions:
        if bp.start <= position <= bp.end:
            label = bp.label or f"byte {bp.start}"
            range_label = (
                f"byte {bp.start}"
                if bp.start == bp.end
                else f"bytes {bp.start}-{bp.end}"
            )
            body = bp.help_text or _no_help_body(
                f":byte {bp.start}-{bp.end} for {rule.tag}"
            )
            return HelpEntry(
                title=f"{rule.tag} {range_label} — {label}",
                body=body,
                source=f"marc-rules.txt {rule.tag} :byte {bp.start}-{bp.end}",
            )
    return None


def _subfield_help(rule: FieldRule, code: str) -> HelpEntry | None:
    sf_rule = rule.subfields.get(code)
    if sf_rule is None:
        return None
    body_parts: list[str] = []
    if sf_rule.help_text:
        body_parts.append(sf_rule.help_text)
    body_parts.append(
        f"_Repeatability: {'repeatable' if sf_rule.repeatability == 'R' else 'non-repeatable'}._"
    )
    return HelpEntry(
        title=f"{rule.tag} ${code} — {sf_rule.label or 'subfield'}",
        body="\n\n".join(body_parts),
        source=f"marc-rules.txt {rule.tag} subfield {code!r}",
    )


def _field_help(rule: FieldRule) -> HelpEntry:
    body_parts: list[str] = []
    if rule.help_text:
        body_parts.append(rule.help_text)
    body_parts.append(
        f"_Repeatability: {'repeatable' if rule.repeatability == 'R' else 'non-repeatable'}._"
    )
    if rule.valid_subfield_codes:
        body_parts.append(
            f"_Valid subfields:_ `{rule.valid_subfield_codes}`"
        )
    if rule.length is not None and rule.length.exact is not None:
        body_parts.append(f"_Length:_ exactly {rule.length.exact} bytes.")
    return HelpEntry(
        title=f"{rule.tag} — {rule.heading}",
        body="\n\n".join(body_parts),
        source=f"marc-rules.txt field {rule.tag}",
    )


def _no_help_body(target: str) -> str:
    return (
        f"_No help text yet for this entry._  "
        f"Add a `:help` continuation under {target} in "
        f"`data/marc-rules.txt`."
    )
