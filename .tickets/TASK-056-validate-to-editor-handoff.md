# TASK-056 — Modal → View-page inline editor handoff

**Status:** Completed
**Stage:** UX integration — wires the Validate / Find / Report
record-detail modals into the single-record `.mrk` editor.

## Title

After TASK-055 a cataloger can open the View-record modal from
Validate and see the issue + the offending field highlighted in
the MRK. There's no path from there to fix it — they have to
remember the record number, manually navigate to the View page,
manually punch the number into the record-# input, then click
"Edit this record" to open the Ace editor. Three steps that
should be one button.

## Scope

* `marcedit_web/render/_record_modal.py`:
  * After the MRK block, render an "✏️ Edit this record" button.
  * On click:
    * `st.session_state["view_index"] = record_index` — preselects
      the record on the View page's number-input navigator.
    * `st.session_state["view_edit_active"] = True` and
      `view_edit_index = record_index` — flips the inline editor
      open on first render, matching the keys
      ``single_record_edit.render_inline_edit`` reads with
      ``key_prefix="view_edit"``.
    * `st.session_state["view_edit_text"] = mrk_writer.render_records_mrk([record])`
      — seeds the Ace buffer with the current record's MRK,
      mirroring the View page's own "open" handler.
    * `st.switch_page("views/1_View.py")` — navigates. The modal
      tears down naturally because Streamlit reruns the app on
      the new page.
* Shared modal placement: the button benefits Find / Report too
  (same "I see something wrong, take me to the editor" intent),
  so we put it in the helper, not just in Validate.

## Success Criteria

1. Clicking "Edit this record" from a Validate modal lands the
   cataloger on the View page with that record selected and the
   inline Ace editor already open, preloaded with the record's
   MRK text.
2. Saving in the inline editor still works exactly as before
   (existing TASK-024 path) and still invalidates
   ``issues_cache`` so the next Validate visit re-runs the
   checks.
3. Find / Report modals show the same button and route the same
   way (no per-page wiring required).

## Out of scope

* Highlighting the issue inside the Ace editor. The editor is
  the cataloger's surface to fix; surfacing the original issue
  message there is a larger change (would need to thread the
  Issue through `render_inline_edit`).
* Auto-saving on navigation. The cataloger explicitly clicks
  Save in the inline editor (unchanged).
