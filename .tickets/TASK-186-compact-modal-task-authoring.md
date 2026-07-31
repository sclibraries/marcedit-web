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

Status: Todo

Design:
- `docs/superpowers/specs/2026-07-31-task-186-compact-modal-task-authoring-design.md`

Plan:
- Not written yet.
