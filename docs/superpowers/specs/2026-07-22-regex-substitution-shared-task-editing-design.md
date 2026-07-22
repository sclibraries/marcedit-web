# Regex Substitution and Shared-Task Editing Design

Ticket: [TASK-172](../../../.tickets/TASK-172-hotfix-regex-substitution-shared-task-editing.md)

## Context

The production-compatible regex option currently uses `re.search` only to
select a matching subfield. Once selected, it replaces the complete subfield
value. Thus matching `TFeba` in `TFeba9780020306634` produces `(SCTFEBA)` and
loses the ISBN suffix.

Shared tasks are deliberately visible and runnable by all signed-in users but
editable only by their owner. Catalogers need to correct a shared form-built
task in place without taking ownership or gaining destructive controls.

## Goals

- Make regex mode perform normal Python regex substitution within the matched
  subfield value, replacing every occurrence and retaining unmatched text on
  either side.
- Preserve exact mode's existing whole-value replacement behavior.
- Let any signed-in cataloger edit the description and operations of an
  existing shared form-built task.
- Let administrators also edit shared hand-written code tasks.
- Preserve the original task owner, name, and shared visibility when a
  collaborator saves.
- Reject a stale collaborative save rather than silently overwrite a newer
  change.
- Audit the acting cataloger and the task owner.

## Non-Goals

- No collaborator list, per-task ACL, approval workflow, or edit history.
- No collaborator rename, unshare, visibility change, or deletion.
- No database schema migration.
- No durable-operation, worker, service, sudoers, Apache, or deployment change.
- No change to the exact-match operation's whole-subfield semantics.
- No change to `main` in this ticket; this is a production-hotfix branch fix.

## Regex Replacement Semantics

`replace_field_subfield_and_indicators` keeps its current signature and
matching constraints for tag, indicators, and subfield code.

- With `regex=False`, the subfield value must equal `match_value`; the complete
  value is replaced by `new_value` exactly as before.
- With `regex=True`, compile `match_value` once before record mutation and use
  `pattern.sub(new_value, subfield.value)`. Every match is replaced. Prefix and
  suffix text outside matches is retained, and normal Python replacement
  capture references are supported.
- `ignore_case` affects regex mode only. Exact mode remains case-sensitive.
- An invalid pattern still fails before any record mutation or task save.
- Indicators and subfield code change only when at least one regex match causes
  the selected subfield to be processed, matching the current field-level
  update boundary.

For the production case:

```text
035 $a TFeba9780020306634
pattern: TFeba
replacement: (SCTFEBA)
new indicator 2: 9
```

the result is:

```text
035 _9 $a (SCTFEBA)9780020306634
```

The form help text will distinguish regex pattern/replacement semantics from
exact whole-value replacement.

## Shared-Task Authorization

The authorization matrix is:

| Actor and task | Edit description/body | Rename | Change visibility | Delete |
| --- | --- | --- | --- | --- |
| Owner | Existing behavior | Yes | Yes | Yes |
| Non-owner, shared form task | Yes | No | No | No |
| Non-owner admin, shared code task | Yes | No | No | No |
| Non-owner non-admin, shared code task | No | No | No | No |
| Non-owner, private task | No visibility or access | No | No | No |

The Tasks list shows an Edit control only when this matrix permits editing.
Collaborative editing opens the existing row but locks the task name and
visibility in the UI. Save-time checks are authoritative: session-state
manipulation cannot rename, transfer ownership, or change visibility.

## Save and Conflict Flow

Opening an existing task stores its owner, immutable identity, and a snapshot
of the persisted editable fields in editor session state. Owner saves continue
through the existing owner path.

A collaborative save uses a dedicated storage function. Inside one SQLite
write transaction it:

1. reloads the row by original owner and name;
2. requires that the row still exists and is still shared;
3. compares its editable fields and visibility with the opened snapshot;
4. rejects the save with an inline stale-edit message if anything changed;
5. updates only description, body, imports, and `updated_at`;
6. leaves owner, name, visibility, and creation time unchanged.

Comparing the actual row snapshot, rather than relying only on the
second-resolution timestamp, avoids same-second lost updates without adding a
revision column. SQLite's write transaction makes the compare-and-update
atomic.

After a successful save, the acting user's visible task directory and registry
are rematerialized as today. Other users see the new version on their next
render/materialization.

## Form and Code Safety

Form editability continues to be derived from the task-builder markers.
Non-admin collaborators can open and save only a form-editable shared task.
Administrators may use the existing Code view for shared code tasks. The
save callback rechecks the actor's admin status and the original task shape so
the UI is not the only guard against collaborative raw-code authorship.

## Errors and Audit

Expected collaborative-save failures appear through the existing inline save
error area and do not partially update SQL or the task registry. Messages cover
task removed, task no longer shared, stale snapshot, and insufficient code-edit
permission.

`task-saved` keeps `user` as the acting cataloger and adds `task_owner` plus a
collaborative-edit flag. An administrator saving shared raw code retains the
existing `admin-action` audit event and also records the task owner.

## Testing

Strict RED/GREEN coverage will prove:

- substring replacement preserves suffix and prefix text;
- every regex occurrence and capture-reference replacement works;
- exact mode still replaces the complete value;
- invalid regex remains non-mutating and rejected before persistence;
- permitted and forbidden cells of the authorization matrix;
- collaborative save preserves owner, name, and visibility;
- stale, unshared, deleted, and unauthorized code saves fail atomically;
- audit data distinguishes actor from owner;
- current owner edit/share/delete behavior remains intact.

The final gate runs the affected task/transform suites, the complete Python 3.9
suite, compilation, a fixed-base scope audit, and independent review before
the hotfix branch is pushed.
