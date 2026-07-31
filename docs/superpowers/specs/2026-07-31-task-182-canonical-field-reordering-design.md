# TASK-182 Canonical MARC Field Reordering Design

**Ticket:** [TASK-182](../../../.tickets/TASK-182-explicit-marc-field-reordering.md)

**Related:** TASK-169

**Status:** Approved

## Purpose

View correctly preserves source order and warns when tags decrease. TASK-182
adds an explicit action that creates a reordered result. Viewing a file never
mutates it.

## Goals

- Provide one stable canonical ordering engine.
- Expose it as a quick action and saved task operation.
- Preview changes before adoption.
- Preserve repeated-field order and fail loud on malformed tags.

## Canonical Order

For each MARC record:

1. Leader remains the record leader and is never treated as a field.
2. Fields sort by their exactly three-digit numeric tag in ascending order.
3. Fields with the same tag retain their original relative order.
4. `880` sorts numerically as `880`; it is not silently paired or moved beside
   its linked field.

Python's stable ordering may be used only behind an explicit tag validator.
The engine does not reorder subfields.

## Malformed Tags

A field tag that is not exactly three ASCII digits is a deterministic error.
The affected operation fails before adoption, identifies record position and
safe tag representation, and drops nothing. Leader and parser failures use the
existing bounded file-error path.

## Shared Engine

One pure transform reorders a deep-copied or candidate record and returns a
summary containing whether it changed and the inversion count. The quick
action and **Sort fields by tag** task step call this same transform. No second
ordering implementation is permitted.

The existing task operation retains its stored kind for compatibility. Its UI
description and reference identify the canonical policy. The task editor may
offer a convenience action to move it to the last position, but task ordering
remains explicit and cataloger-controlled.

## Preview

Preview is non-mutating and reports:

- total records inspected and changed;
- total tag inversions corrected;
- malformed records;
- bounded representative before/after field sequences; and
- the first bounded full MARC examples when useful.

An already ordered file reports no changes and produces no new adopted
version. Serializer differences are measured in tests and documented; the
operation must not claim byte identity where pymarc necessarily normalizes
serialization.

## Adoption and History

Quick action uses the existing candidate-output, version, snapshot, history,
and rollback workflow. Task execution uses the existing sandbox/candidate
path. Failure or cancellation adopts no partial output.

## Testing

Tests cover Leader placement, control/data ordering, stable duplicates, 880,
already ordered records, reverse order, malformed tags, empty records,
serializer behavior, non-mutating preview, quick/task equivalence, history,
rollback, and task save/reopen.

Focused and complete mounted-source Docker suites report every skip. Compiler
contract freshness is verified if generated task output changes. Independent
review must find no unresolved Critical or Important issue.

## Rollout

No route, service, worker, proxy, authentication, database schema, or
ITS-managed configuration change is required.
