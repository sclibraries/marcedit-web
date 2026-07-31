# TASK-185 External Task Migration Design

**Ticket:** [TASK-185](../../../.tickets/TASK-185-external-find-replace-migration.md)

**Depends on:** TASK-180 and TASK-184 for structural mappings

**Status:** Approved

## Purpose

External task files mix instructions the application can translate exactly
with proprietary, ambiguous, or whole-line expressions whose semantics are not
equivalent to the native engine. TASK-185 replaces all-or-nothing rejection
with a fail-closed Migration review draft while converting only proven
signatures.

## Goals

- Preserve every source instruction in original order.
- Convert only losslessly equivalent signatures.
- Make unresolved meaning visible and repairable by a cataloger.
- Retain local provenance without publishing institutional record content.
- Never claim universal MarcEdit compatibility.

## Non-Goals

- Executing `.mrk` whole-line regex through the native value-level regex path.
- Guessing external numeric flags, Boolean options, or regex dialects.
- Saving or running a draft with unresolved instructions.
- Copying or redistributing proprietary code or implementation artifacts.

## Migration Review Draft

Import parsing produces an ordered review draft rather than immediately saving
a task. Each source instruction becomes one of:

- **Converted:** an editable structured native operation;
- **Choice required:** a blocking card with explicit cataloger choices; or
- **Unresolved:** a blocking card with original instruction and reason.

Converted and blocking cards remain in source order. Catalogers may edit
converted operations or replace a blocking card with one or more explicit
operations. Save, compilation, and execution remain disabled until no blocking
card remains. Cancel discards the review draft and saves nothing.

## Provenance

Every card retains source format, source line number or archive-entry location,
instruction digest, and classification. Original instruction text remains in
the session-local migration audit and blocking card. Portable task definitions
do not embed full institutional source files or record content.

## Adapter Registry

One deterministic adapter registry owns supported signatures. Each adapter
declares:

- exact verb and complete accepted shape;
- field/value target;
- match and replacement semantics;
- case, occurrence, and preservation behavior;
- required TASK-180 or TASK-184 native operation; and
- synthetic characterization fixtures proving equivalence.

An adapter either returns one or more exact structured operations or declines
with a reason. Partial parsing is not conversion.

Known structural signatures such as a complete, proven 856 indicator/tag
rewrite may convert. Arbitrary regular expressions over complete `.mrk` lines,
unproven `^b`, unknown numeric options, and unknown flags remain unresolved.
The native raw-regex editor does not serve as an escape hatch because it
operates on selected MARC values, not serialized mnemonic lines.

## Empty-Find Instructions

An empty-find `SUBFIELD_EDIT` is never executed as Python empty-string
replacement. It becomes **Choice required** with exactly:

- add the value only when the subfield is missing;
- replace existing values; or
- ensure exactly one occurrence.

The selected meaning becomes a normal structured operation and is preserved in
the migration audit. No option is preselected.

## Archive Behavior

Each archive entry receives its own review result. Valid entries may open as
separate review drafts, but no entry is silently saved. Archive validation and
quota errors remain archive-level failures. TASK-187 keeps the complete result
visible across reruns.

## Failure Handling

- Unknown syntax remains blocking and visible.
- Adapter exceptions are bounded to the instruction and logged; they do not
  silently downgrade to conversion.
- Losing source order or provenance is an import failure.
- A changed adapter version never silently rewrites an already saved task.
- Existing saved legacy code remains unchanged until a cataloger explicitly
  opens and confirms a migration review.

## Corpus and Testing

Committed tests use sanitized synthetic fixtures for every accepted signature,
near miss, ambiguous flag, empty-find choice, and unresolved case. The real
`MarcEdit Tasks/` corpus remains untracked and local. A local corpus audit
classifies every line and loudly skips when the corpus is absent; committed
guarantees never depend on that audit.

Tests prove adapter/native execution equivalence, ordered review drafts,
provenance, blocking save/run gates, explicit choices, cancel, archive entry
isolation, and lossless save/reopen after resolution. Focused and complete
mounted-source Docker suites report every skip. Independent review must find
no unresolved Critical or Important issue.

## Rollout

No production route, service, worker, database schema, authentication, or ITS
configuration changes are required unless implementation discovers a storage
need not represented in the approved design; such a discovery blocks the task
rather than expanding it silently.
