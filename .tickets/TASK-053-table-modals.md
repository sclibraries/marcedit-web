# TASK-053 — Full-record modals on virtualized tables

**Status:** Completed
**Stage:** UX cleanup pass — addresses the "content cut off" pain.

## Title

Three virtualized tables truncate content the cataloger needs to
read in full:

* **Validate** — ``message`` and ``suggestion`` columns wrap or
  ellipsize. The cataloger can't see the full record the issue
  applies to without leaving the page.
* **Report** — per-record table truncates ``title`` to 120 chars.
  No record-detail affordance.
* **Find** — title + match snippet truncated to 80 chars. No
  detail affordance.

Each gets a "View record" modal showing the full MRK-rendered
record plus the issue/error context. Validate also gets severity
color coding so the eye can spot errors without scanning a
greyscale column.

## Scope

- **Dialog helper** ``marcedit_web/render/_record_modal.py``:
  * ``open_record_modal(record_index: int, *, store, header,
    extra_lines=None)`` — ``@st.dialog``-decorated function. Pulls
    the record from the store, renders via ``mrk_writer``, shows
    the index + identifier in the header. Optional
    ``extra_lines`` is a list of (label, body) tuples shown above
    the MRK block (used by Validate to surface the issue message
    + suggestion).
  * Centralized so all three tables look the same.
- **`marcedit_web/render/validate.py`**:
  * Add ``on_select="rerun"`` + ``selection_mode="single-row"`` to
    the issue ``st.dataframe`` call.
  * Below the table: when a row is selected, render a "View
    record #N" button that opens the dialog with the matching
    record, the issue's ``message``, and its ``suggestion``.
  * Severity color: pandas Styler applies background colors
    (``#fecaca`` for error, ``#fde68a`` for warning, ``#dbeafe``
    for info) to the severity cell so the column reads at a
    glance.
- **`marcedit_web/render/report.py`**:
  * Same selection + "View record" pattern on the per-record
    table.
- **`marcedit_web/render/find.py`**:
  * Same. The Find page already has "Open first match in View" —
  the modal is the per-row complement.
- **Tests:** dialog behavior is hard to unit-test under Streamlit
  (the decorator wires up a runtime context). Coverage relies on
  the existing render-module tests still passing + a manual
  browser smoke. Add a small unit test on the styling helper to
  guard the color map.

## Out of scope

- Editing the record from the modal. Read-only view; the cataloger
  can navigate to MarcEditor to edit.
- Modal access from the MarcTools CSV preview. That table is
  flatten-for-export shaped; it doesn't represent records 1:1 so
  a record modal is the wrong fit.
- Restructuring the table-on-select state machine to handle
  open/close transitions perfectly — use the "select then click
  View" two-step to sidestep Streamlit's persistent-selection
  quirk.

## Success Criteria

1. Click a row in Validate's issue table → a "View record" button
   appears. Clicking it opens a modal showing the full MRK record
   plus the full issue message and suggestion text.
2. Severity column in Validate is visibly color-coded (red /
   amber / blue).
3. Same select-then-view flow works on Report and Find.
4. Closing the modal returns to the table with the selection
   intact (so the cataloger can re-open or pick the next row).
5. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
# Browser smoke: validate a small batch, click an issue row,
# verify modal contents.
```
