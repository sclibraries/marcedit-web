# TASK-186 Compact Modal Task Authoring Design

**Ticket:**
[TASK-186](../../../.tickets/TASK-186-compact-modal-task-authoring.md)

**Status:** Approved design; implementation plan not yet written.

## Context

TASK-179 and TASK-180 made structured operation authoring safer and more
explanatory, but each operation currently renders its complete controls,
technical details, preview, and actions inline. A task with several operations
becomes a long page that catalogers must continuously scroll while losing sight
of the task as an ordered recipe.

The project already uses large Streamlit dialogs for record comparison and
other focused workflows. Docker currently resolves Streamlit 1.50.0, whose
dialog API supports `width="large"`, `dismissible=False`, and dismissal
callbacks. The repository dependency still permits Streamlit 1.37, so the
implementation must raise the application requirement to
`streamlit>=1.50,<2` and verify that contract rather than assuming every
previously allowed version supports it.

## Goals

- Make a multi-operation task readable without expanding every form.
- Give one operation enough space for guided controls and MARC preview.
- Preserve plain-language meaning, validation, and preview state on the main
  task page.
- Make Add/Edit transactional so cancellation never mutates the task draft.
- Apply one interaction model to every form-mode operation.
- Reuse deterministic operation semantics rather than introducing a second
  editor, validator, preview engine, or storage representation.

## Non-Goals

- Changing code mode.
- Changing operation parameters, compiler output, task storage, execution, or
  preview semantics.
- Adding AI-generated operations or changing existing AI behavior.
- Converting unresolved imported instructions automatically.
- Redesigning the entire Tasks workspace or its Run, Results, History, and
  Quick tools modes.
- Changing authentication, authorization, sharing, workers, services, routes,
  deployment topology, cron, or ITS-managed startup configuration.
- Completing the full cataloger operation guide owned by TASK-183.

## Main Task Page

Form mode shows only:

1. task metadata such as name and visibility;
2. the ordered compact operation-card list;
3. **+ Add operation**;
4. **Browse operation reference**; and
5. task-level **Save task** and **Cancel** actions.

The existing operation dropdown moves off the page. **+ Add operation** opens
the operation dialog with an alphabetical cataloger-facing type selector at
the top. Selecting a type displays its setup controls below in the same dialog;
dialogs never nest.

Code mode retains its existing editor and behavior.

## Compact Operation Cards

Every form-mode operation uses the same card shell. Each card shows:

- its ordinal position and cataloger-facing operation name;
- one plain-language summary of the current intent;
- a concise target badge when a meaningful target exists;
- validation status: **Valid** or **Needs attention**;
- preview status when supported: **Not previewed**, **Current**, **Stale**, or
  **Failed**; and
- **Edit**, move up, move down, and **Remove** actions.

Cards do not show the complete form, technical parameter dump, generated code,
or full before/after MARC. Those belong in the dialog. Reordering changes only
operation order; it does not rewrite parameters or invalidate request-keyed
preview evidence.

Invalid, future-version, custom, and unresolved imported operations remain
visible. Their card says **Needs attention** and preserves their existing
technical representation. Nothing silently guesses or converts their meaning.

## Add and Edit Dialog

One large dialog component handles both adding and editing:

- **Add** begins with defaults for the selected operation type.
- **Edit** deep-copies the selected operation.
- Widgets mutate only the modal draft.
- **Keep in task** inserts or replaces one operation in the ordered task draft.
- **Cancel** leaves the ordered task draft unchanged.
- When the draft differs from its opening value, Cancel shows an explicit
  discard confirmation before closing.

The dialog is non-dismissible: X, escape, and outside-click closure do not
silently discard work. Streamlit's dialog capability is a runtime contract.
The implementation must require `streamlit>=1.50,<2` and add a
preflight/contract test asserting `dismissible` is present in
`inspect.signature(st.dialog).parameters`; it must not silently degrade to
unsafe dismissal. Both `requirements.txt` and `pyproject.toml` change. This is
an application dependency update and requires no ITS-managed service
definition or startup change.

Dialog titles name Add or Edit and the selected cataloger-facing operation.
Because existing repository dialogs use static decorators, the implementation
must deliberately create the wrapper at runtime with
`st.dialog(title, width="large", dismissible=False)(render_function)` and
invoke only that one dialog wrapper in the script run.

Each modal opening receives a fresh widget-key namespace. Modal state contains
the mode (add/edit), source index when editing, selected kind, opening value,
working copy, and a monotonically increasing nonce. Operation parameters do
not gain UI-only identifiers, and task serialization remains unchanged.

## Dialog Tabs

The dialog separates concerns into tabs:

- **Set up** contains editable cataloger-facing controls and actionable
  validation messages.
- **Preview** contains the complete before/after MARC view, counts, preview
  errors, and refresh action when that operation supports preview.
- **Technical details** contains stored parameters, generated matching
  behavior, unresolved source information, and documentation links when those
  details exist.
- **Reference** contains the selected operation's read-only reference entry
  and syntax-documentation link without opening another dialog.

Tabs that have no meaningful content are omitted. Simple operations therefore
show only **Set up** and **Reference** rather than empty Preview or Technical
tabs. Existing operation-specific renderers remain authoritative inside the
tab shell after receiving the correct caller-provided rerun behavior.

## Drafts, Validation, and Save Gates

**Keep in task** may retain an incomplete or invalid modal draft. This is a
task-authoring draft action, not execution authorization. The resulting card
shows **Needs attention**, allowing the cataloger to work elsewhere without
losing entries.

Task-level **Save task** validates every operation with the existing
operation-specific validators. It refuses to save while any card needs
attention, identifies the affected ordinal cards, and provides an Edit action.
Existing execution and submission gates remain defense in depth and continue
to reject unresolved or unsafe operations.

Raw-regex syntax, capture-reference, and current-preview requirements retain
their TASK-180 meanings. Imported unresolved Add/Build instructions retain
their existing submission block. The modal shell cannot turn an invalid draft
into executable code.

Unexpected renderer or preview failures are caught at the dialog boundary and
shown as bounded actionable errors. The working copy remains available; the
Tasks page must not crash or discard it.

## Preview Identity and Status

Existing request-keyed preview caching remains authoritative. Preview currency
continues to depend on the normalized request, store identity, and store
revision. Moving a card does not affect any of those values. Editing parameters
or changing the source marks prior evidence stale.

Cards show status only. Full evidence stays in the Preview tab so stale or
partial MARC output does not make cards tall or misleading.

## Operation Reference Dialog

**Browse operation reference** opens a separate read-only large dialog. It is
reachable only from the main task page because Streamlit prohibits opening a
second dialog during the same script run. Operations are alphabetical by
displayed label and include the current short summary.

The dialog provides a case-insensitive text filter over displayed operation
labels and summaries using native Streamlit controls and no custom JavaScript.
The already-open Add/Edit operation dialog presents the selected operation's
same content in its **Reference** tab. It never calls the separate dialog,
never nests dialogs, and never changes task state.

## Component Boundaries

The implementation keeps `render/tasks.py` as the coordinator rather
than growing another full editor inside it:

- a focused card renderer owns card presentation and card actions;
- a focused operation-dialog renderer owns temporary draft state, tabs,
  dismissal safety, and Keep/Cancel transitions;
- existing task-authoring renderers own operation-specific controls and accept
  an optional rerun callable that defaults to `st.rerun` for current inline
  callers;
- existing validators, summaries, compiler, and preview helpers remain the
  single sources of behavioral truth; and
- a focused read-only reference dialog owns alphabetical browsing.

The modal caller supplies a rerun callable that uses
`st.rerun(scope="fragment")` for operation-control interactions. A renderer
must not hardcode fragment scope: fragment rerun is invalid during a full-app
rerun and would break existing inline callers. Keep, Cancel, and other actions
that intentionally close the dialog continue to request a full-app rerun. All
eight current `st.rerun()` sites in `render/task_authoring.py` are routed
through the injected callable, covering Add/Build row and segment actions plus
guided mode transitions.

No generic abstraction should be introduced beyond what the shared card and
dialog shells require. Simple operation renderers continue using the current
palette parameter definitions.

## Accessibility and Interaction

- Dialog titles name Add or Edit and the selected operation.
- Buttons use text labels; arrows retain accessible help text.
- Status is conveyed with words as well as color.
- The operation selector for Add and first setup control for Edit are rendered
  first in DOM order, making them the first natural keyboard tab stops;
  Streamlit provides no programmatic focus API.
- Keyboard users can traverse every control and reach Keep/Cancel.
- Destructive Remove and dirty Cancel require confirmation.
- The operation order remains visible outside the dialog.

## Testing

Intent-focused tests cover:

- Add selecting a type, keeping a valid operation, and keeping an incomplete
  draft;
- Edit isolation, Keep replacement, clean Cancel, and dirty-Cancel
  confirmation;
- non-dismissible dialog configuration and the minimum Streamlit contract;
- runtime dialog-title wrapping with exactly one dialog invocation per script
  run;
- identical operation-renderer behavior under default app reruns and injected
  dialog-fragment reruns, including every current add/move/remove and guided
  mode-switch path;
- fresh widget namespaces across modal openings and reordered operations;
- every form-mode operation kind entering the shared modal shell;
- card summaries, target badges, validation states, and preview states;
- current preview surviving reorder and becoming stale after parameter/source
  changes;
- invalid and unresolved cards blocking task save and execution without data
  loss;
- Add selector and standalone operation-reference alphabetical order;
- the in-dialog Reference tab and standalone reference dialog sharing content
  without nesting dialogs or mutating task state;
- unchanged code mode, form serialization, compiler output, AI boundaries,
  imports, sharing, and execution behavior; and
- failure containment when one dialog renderer or preview raises.

Docker browser acceptance builds a synthetic task with several real-world
operations, edits and reorders them, retains one incomplete draft, previews a
guided replacement, resolves the draft, saves/reopens, and confirms that the
main page remains a compact ordered list without continuous form scrolling.
Every skipped check is reported.

## Rollout and Dependencies

TASK-180 must be merged first. TASK-186 receives its own isolated worktree and
implementation plan. Before changing UI behavior, the implementation records
characterization tests for current save, serialization, preview, import, AI,
and code-mode behavior.

The modal redesign does not require an ITS service-file, systemd, proxy,
directory, or routing update. If the deployed Python environment lacks the
required Streamlit 1.50 dialog contract, application dependency installation
from the updated `requirements.txt` and `pyproject.toml` must correct it before
rollout; the signature preflight fails loud rather than starting a partial or
unsafe modal implementation.

## Alternatives Considered

### Compact list with persistent side editor

This reduces modal opening but gives complex guided controls and MARC preview
too little width, especially on smaller screens.

### Step-by-step modal wizard

This minimizes visual density but adds more clicks and hides relationships
between settings. It is unnecessary because progressive controls already hide
irrelevant fields.

### Inline mini-previews on every card

This keeps evidence visible but recreates tall cards and makes stale preview
content easy to mistake for current results. Status belongs on cards; evidence
belongs in the Preview tab.
