Title: Job files table action buttons and headers stack/wrap at realistic widths

Scope:
- `render_job_files_table` (marcedit_web/render/job_files.py) gives the
  Open, "History & review", and ⋮ controls their own proportional grid
  columns (weights 1, 1.5, 0.6 of 13.6). Inside the Jobs detail page the
  table also sits in the `[4,1]` files column, so at realistic viewport
  widths those columns fall below the buttons' content width and
  Streamlit's break-word wrapping stacks the labels letter-by-letter
  ("O/p/e/n"). The "Version" and "Records" headers (weight 1) wrap
  mid-word ("Versi/on", "Reco/rds") the same way.
- Root cause class already documented in TASK-146: proportional
  `st.columns` cannot declare a minimum width.
- Fix (as implemented):
  - Merge the three action columns into one wider trailing column laid
    out with a horizontal content-width container, so buttons wrap as
    whole units, never letter-by-letter. Grid becomes
    `[3, 1.5, 1.4, 1.4, 2, 2, 4.5]` with one weight per header.
  - Runtime measurement showed the TASK-152 `[4,1]` side-by-side detail
    split leaves the table only ~635px at a 1250px viewport — no
    weighting can fit the row there. The Files section now gets the full
    content width; "Next handoff" moves below it in a compact `[1,2]`
    column, preserving TASK-152's files-first hierarchy (files before
    handoff before tabs).
  - Shorten the row button label "History & review" → "History"; the
    longer label alone forced the action row onto two lines at common
    widths. The destination page keeps its "History & review — {file}"
    heading, and docs/jobs.md never names the button.
- Popover/permission logic unchanged.

Success Criteria:
- Table grid and headers stay in sync (one weight per header).
- Action controls render inside a horizontal content-width container,
  not dedicated narrow proportional columns; a test pins this so the
  letter-stacking regression cannot silently return.
- Existing table behavior tests (open, history, popover gating) pass
  unchanged in both Home and Jobs page suites.
- Runtime before/after verification in the browser at the reported
  width: button labels on one line per button, headers not split
  mid-word.

Verification:
- In-image suite (worktree mounted, scripts/ included): 1245 passed,
  12 skipped (env-conditional deploy tests).
- Host deploy-file tests: 13 passed.
- Browser (Playwright via header-injecting proxy, signed in as
  roconnell@smith.edu, isolated smoke instance):
  - Before: at a 1250px viewport the Jobs detail Files table rendered
    "O/p/e/n" letter-stacked buttons and "Versi/on", "Reco/rds" headers.
  - After: at 1360px (the reported geometry) Open / History / ⋮ sit on
    one line with every header on one line, on both the Jobs detail and
    Home Job Workspace tables; at 1250px the ⋮ trigger alone wraps as a
    whole unit. ⋮ popover opens (Check out) and History navigates to
    History?job_file=1.

Status: In-Progress
