# TASK-061 — Polish deterministic note parser review output

**Status:** Completed

## Title

Fix confusing review output from deterministic cataloger-note task drafts.

## Scope

- Avoid deriving task names from structural headings such as Find/replace.
- Strip explanatory parenthetical comments from MarcEdit-style find/replace
  values before creating replacement operations.
- Render subfield-code explanations without Markdown dollar-sign artifacts.
- Preserve ambiguous 035 and colon-only 300 cleanup lines for review unless a
  safe deterministic mapping exists.

## Success Criteria

1. Notes that start with Find/replace fall back to `draft-from-notes` rather
   than `find-replace`.
2. Proxy URL find/replace lines with `(ie, OLD PROXY)` comments produce clean
   find/replace values.
3. Generated operation summaries display readable 856 subfield wording.
4. Focused tests pass.
