# TASK-055 — Validate: explicit View button + line highlight in modal

**Status:** Completed
**Stage:** UX cleanup — Validate page modal trigger.

## Title

The Validate page's `st.status("Validating records…")` spinner
fires on every rerun — including the rerun caused by clicking a
row in the issue table. So the visual "I'm validating" feedback
re-appears every time the cataloger just wants to peek at a
record's full MRK. Cataloger has to wait through the same status
animation twice for a single browse action.

Separately, the row-selection affordance is the dataframe
selection indicator (Streamlit renders this as a checkbox-style
column). That doesn't read as "click to view"; the cataloger
asked for an explicit "View" button.

## Scope

* `marcedit_web/render/validate.py`:
  * Memoize the preflight + rules pass in
    `st.session_state["issues_cache"]["validate"]`. The dict is
    cleared by `session.handle_upload` and by the Edit/Tasks/
    Fixed-Field paths, so the existing invalidation hooks already
    cover all record-mutating cases.
  * Run the `st.status("Validating records…")` block only when
    that cache is empty.
  * Drop `selection_mode="single-row"` + `on_select="rerun"` from
    `st.dataframe` so the row-selection column goes away. The
    table becomes a read-only overview.
  * Below the table: render a `selectbox` of the filtered
    record-scope issues + a "View" button. Click → opens the
    record modal directly with the chosen issue's record index.
  * Derive the MARC field tag the issue refers to (helper
    `_tag_for_issue`) and pass it to the modal so it can shade
    the matching `=TAG` line.

* `marcedit_web/render/_record_modal.py`:
  * Add optional `highlight_tag` and `highlight_severity`
    parameters to `open_record_modal`. Defaults preserve the
    plain `st.code` rendering (Find and Report don't pass them).
  * Wrap `store.get(...)` in a small `st.spinner` so the modal
    opens immediately and shows progress inside while pymarc
    loads the record from disk. Previously the user saw nothing
    until the record was ready.
  * When `highlight_tag` is provided, render the MRK via a small
    `<pre>` block with the matching line shaded by
    severity-themed colors. Non-matching lines render plain.

* Tests:
  * `tests/test_validate_view_button.py` — cover
    `_tag_for_issue` (code-map hits, message-prefix regex hits,
    record-scope/file-scope None returns) and the MRK highlight
    HTML helper (`_render_mrk_highlighted` shades matching
    `=TAG` lines, leaves others alone).

## Success Criteria

1. Clicking the View button opens the modal **without** the
   page-level "Validating records…" status spinner reappearing.
2. The dataframe no longer shows the row-selection checkbox
   column.
3. The modal shows a spinner inside itself while the record is
   being loaded; the `=TAG` line that triggered the selected
   issue is shaded (yellow for warning, red-tint for error,
   blue-tint for info).
4. Find and Report pages still render their record modals
   exactly as before — the `highlight_tag` / `highlight_severity`
   defaults preserve the prior plain `st.code` view.
5. All existing tests in `tests/test_validate_styling.py` and
   `tests/test_rules_validate.py` still pass.

## Out of scope

* Editing the record from the modal. Read-only view (TASK-053
  decision still stands).
* Highlighting subfield-level location inside a field. The first
  cut targets only the `=TAG` line; per-subfield underline can
  follow if the cataloger asks for it.
* Refactoring Find/Report to use the same View-button pattern.
  Those pages have different data shapes; we can revisit if the
  Validate change lands well.
