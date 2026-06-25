# TASK-057 — Inline `.mrk` editor: Ace gutter annotations

**Status:** Completed
**Stage:** UX polish — inline editor surfaces validation results
where the cataloger is already looking.

## Title

The View page's inline single-record editor
(`single_record_edit.render_inline_edit`) already validates on
every keystroke (parse + per-record preflight + rule checks),
but the results render in a separate ``Validation: N fatal, M
warning, K info`` expander below the buffer. The cataloger has
to mentally map "line 7 in the editor" to "the warning about
245 ind1" instead of seeing it gutter-marked right next to the
line.

The Workspace Edit (MarcEditor) page already does this — passes
``annotations=`` to ``st_ace`` so errors show as red/yellow/blue
gutter markers tied to the offending row. Lift the same pattern
into the inline editor.

## Scope

* `marcedit_web/render/single_record_edit.py`:
  * Build `annotations: list[dict]` from
    `SingleRecordParseResult.line_errors` (carry `line_no` +
    `column`) and `result.rule_issues` (per-record issues; pull
    the tag from the message and map to the editor's `=TAG` row).
  * Pass `annotations=annotations` to the `st_ace` call.
  * Marker `type` is `"error"` for fatal codes + severity=error,
    `"warning"` for severity=warning, `"info"` for severity=info.
* `marcedit_web/render/validate.py`:
  * Extract `_tag_for_issue` + `_CODE_TO_TAG` + regexes to
    `marcedit_web/lib/issue_tags.py` so both validate.py and
    single_record_edit.py can use the same tag-extraction logic.
  * Re-export from validate.py to keep
    `tests/test_validate_view_button.py` working without churn.

## Success Criteria

1. Typing an invalid MARC line in the inline editor surfaces an
   Ace gutter marker on that line, with the parser's error code
   in the marker tooltip.
2. Rule-validation warnings (e.g. ``245 ind1 = '5'``) show as
   yellow gutter markers on the matching `=245` line.
3. The existing "Validation: …" expander still renders below as
   a text fallback; closing the expander doesn't hide the gutter
   markers.
4. Tests in `test_validate_view_button.py` still pass after the
   tag-extraction extraction.

## Out of scope

* Stricter fixed-field byte-level validation (LDR/05-08, 008
  date / language). Separate ticket — needs MARC21 byte tables
  or a rules-format extension.
* Required-subfield highlighting. Separate ticket — needs a new
  field in `SubfieldRule` plus a rules-file syntax extension
  plus validator support.
