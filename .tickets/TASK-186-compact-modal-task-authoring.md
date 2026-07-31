Title: Replace scrolling task forms with compact cards and operation dialogs

Parent: TASK-174

Depends On: TASK-180

Scope:
- Replace expanded inline form-mode operation editors with compact ordered
  cards and one large Add/Edit operation dialog.
- Apply the same card/dialog shell to every form-mode operation while reusing
  existing operation controls, validation, preview, compiler, and execution
  behavior.
- Put editable controls, preview evidence, and technical details into focused
  dialog tabs when those surfaces apply to the selected operation.
- Add a read-only alphabetical operation-reference dialog on the task page and
  a Reference tab inside the already-open Add/Edit operation dialog.
- Update `requirements.txt` and `pyproject.toml` to require
  `streamlit>=1.50,<2`, and adapt operation renderers to accept the correct
  app- or fragment-scoped rerun behavior from their caller.
- Preserve incomplete or unresolved operation drafts visibly and losslessly;
  block final task save and execution until every operation is valid.
- Keep code mode, task storage, generated Python, AI drafting, imports,
  authorization, worker behavior, deployment services, and ITS configuration
  unchanged.

Success Criteria:
- A multi-operation task is readable as a short ordered list without every
  operation's controls rendering inline.
- Add operation opens one dialog that begins with an alphabetical operation
  selector and then renders that operation's controls.
- Edit uses an isolated draft; Keep in task commits it, while Cancel preserves
  the previous operation and confirms before discarding dirty state.
- Cards show a plain-language summary, validation/preview status, concise
  target information, and edit/reorder/remove actions.
- Modal tabs separate Set up, Preview, Technical details, and Reference;
  unsupported tabs are omitted rather than empty.
- Invalid and unresolved operations remain visible as Needs attention cards,
  but task save and execution fail loud until corrected.
- Operation and preview meaning survives reordering, save/reopen, imported
  task review, and modal cancellation without stale widget-state leakage.
- The application requires `streamlit>=1.50,<2` for safe non-dismissible
  dialogs; dependency and preflight checks fail loud if unavailable.
- Existing operation renderers behave identically inside and outside the
  dialog shell, including add/move/remove and mode-switch reruns; fragment
  reruns fall back safely to app scope when fragment context is unavailable.
- Cancel restores the original operation's preview status and never presents
  preview evidence generated only for a discarded modal draft as current.
- Focused and complete Docker suites pass with every skip reported, and
  cataloger browser acceptance confirms substantially reduced page scrolling.
- Independent review has no unresolved Critical or Important findings.

Status: In-Progress

Design:
- `docs/superpowers/specs/2026-07-31-task-186-compact-modal-task-authoring-design.md`

Plan:
- `docs/superpowers/plans/2026-07-31-task-186-compact-modal-task-authoring.md`

Verification checkpoint (2026-07-31):
- Reviewed implementation head: `d0c5a8e` (title correction after `235f4ca`).
- Rebuilt candidate image:
  `sha256:87bae70bb6349dd033cde397ac88bba32de0483d5b3bb73349f23599047a97ec`.
- Dependency preflight: Streamlit `1.50.0`; the live `st.dialog` signature
  includes `dismissible`, so the non-dismissible dialog capability assertion
  passed.
- Rebuilt image-only complete suite: 1,931 passed, 8 failed, and 39 skipped in
  86.89 seconds. The eight known failures require repository identity files
  omitted from `/app` (`README.md`, `Dockerfile`, the TASK-176 ticket, and the
  TASK-174 phase-one plan). All 39 build-context, Docker-CLI, reference, and
  absent-corpus skips are itemized in the browser evidence.
- Read-only mounted-source complete suite: 1,973 passed, zero failed, and 5
  skipped in 81.47 seconds. Four skips require a Docker CLI inside the
  networkless container; one skip requires the unavailable institutional
  MarcEdit Tasks corpus. Synthetic fixtures remain authoritative.
- Native compiler freshness guard: 1 passed in 0.09 seconds; the checked-in
  compiler contract has no diff from `main`.
- Browser acceptance: 0 passed, 0 failed, and 14 skipped. The required
  `browser-use` executable was absent and the approved in-app browser
  controller was not exposed, so no browser assertion or role-specific
  workflow was treated as passed. No screenshot was captured.
- Evidence:
  `docs/superpowers/evidence/task-186-compact-modal-task-authoring-browser-smoke.md`.
- Independent review: one Important Add-title finding was reproduced with a
  failing focused test and resolved by `d0c5a8e`; the 106-test focused modal
  suite passed. Re-review against the corrected TASK-186 implementation range
  reported zero Critical, Important, or Minor findings and assessed the
  implementation as ready.
- Disposition: `DONE_WITH_CONCERNS`. The ticket remains `In-Progress` because
  the cataloger browser gate is incomplete. TASK-174 is not advanced.

Post-checkpoint corrective review (2026-07-31):
- Whole-branch review found three Important issues: cross-editor removal
  confirmation state, malformed non-object operation parameters, and stale
  failed-preview status after a source change.
- Commit `f842453` corrected all three and added nested deep-copy coverage.
  Re-review found one no-file preview-status edge case; commit `dd9f364`
  corrected it with a regression test.
- Final focused Docker suite: 121 passed and zero skipped.
- Final read-only mounted-source complete suite: 1,979 passed, zero failed,
  and 5 explicitly reported skips (four Docker-CLI checks unavailable inside
  the container and one unavailable institutional corpus check).
- Final independent re-review reported no unresolved Critical or Important
  findings and assessed the code as ready for real browser acceptance.
- Browser acceptance remains 0 passed, 0 failed, and 14 skipped. The ticket
  remains `In-Progress`; TASK-174 is unchanged and merge/release readiness is
  still blocked by that browser gate.
