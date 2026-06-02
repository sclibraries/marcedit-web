"""Build ``st_ace`` gutter annotations from a parse + validate pass.

This lives in ``lib/`` rather than ``render/`` so the unit tests can
exercise the pure logic without ``streamlit_ace`` installed on the
host — the render-layer module imports st_ace at module scope, which
breaks test collection on dev machines that only have the
``streamlit`` core wheel.

The output is a list of dicts in exactly the shape ``st_ace`` reads:
``{"row": int, "column": int, "type": "error"|"warning"|"info",
"text": str}``. Used by
:func:`marcedit_web.render.single_record_edit.render_inline_edit` to
gutter-mark each issue next to the line it refers to.
"""

from __future__ import annotations

from typing import Any

from . import issue_tags, view_edit


def editor_row_for_tag(text: str, tag: str) -> int | None:
    """Return the 0-based row of the first ``=TAG`` line in ``text``.

    ``None`` if no matching line exists (e.g. the issue is
    ``missing-856`` and the record has no 856 — the cataloger has to
    add the line, so callers anchor to row 0 in that case).

    Match requires the tag prefix to be followed by whitespace or
    end-of-line so a request for ``"00"`` doesn't collide with
    ``=001`` / ``=008``.
    """
    prefix = f"={tag}"
    for i, line in enumerate(text.splitlines()):
        if line.startswith(prefix) and (
            len(line) == len(prefix) or line[len(prefix)].isspace()
        ):
            return i
    return None


def build_annotations(
    text: str, result: Any | None,
) -> list[dict]:
    """Build ``st_ace`` annotation dicts from a parse + validate pass.

    Two sources feed the gutter:

    * ``result.line_errors`` — parser-level issues that already carry
      the exact ``line_no`` (1-based) and ``column`` (0-based) of
      the offending text. Promoted to ``"error"`` when the code is
      in ``view_edit._FATAL_LINE_CODES`` (those block Save);
      ``"warning"`` otherwise.
    * ``result.rule_issues`` — per-record preflight / rule warnings
      that don't carry a line number. We derive the relevant MARC
      tag via :func:`issue_tags.tag_for_issue` and look up the
      matching ``=TAG`` row. If the tag isn't in the buffer
      (e.g. ``missing-856``), we anchor at row 0 so the cataloger
      still sees the marker.
    """
    if result is None:
        return []
    out: list[dict] = []

    for err in result.line_errors:
        out.append({
            "row": max(0, err.line_no - 1),
            "column": max(0, err.column),
            "type": (
                "error" if err.code in view_edit._FATAL_LINE_CODES
                else "warning"
            ),
            "text": f"{err.code}: {err.message}",
        })

    for iss in result.rule_issues:
        tag = issue_tags.tag_for_issue(iss)
        row = editor_row_for_tag(text, tag) if tag else None
        ace_type = (
            "error" if iss.severity == "error"
            else "warning" if iss.severity == "warning"
            else "info"
        )
        out.append({
            "row": row if row is not None else 0,
            "column": 0,
            "type": ace_type,
            "text": f"[{iss.severity}] {iss.code}: {iss.message}",
        })

    return out
