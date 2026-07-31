# TASK-181 Explicit RDA Operations Design

**Ticket:** [TASK-181](../../../.tickets/TASK-181-explicit-rda-operations.md)

**Status:** Approved

## Purpose

`RDAHELPER` is an opaque external instruction whose full behavior is not
proven. TASK-181 does not emulate it. It provides transparent deterministic
RDA-oriented operations based on open MARC21/RDA rules and explicit Smith
policy.

## Goals

- Expose independently selectable and documented RDA operations.
- Offer an optional visible Smith RDA cleanup profile composed of those
  operations.
- Support deterministic material classification with preview and override.
- Keep ambiguous external settings unresolved.

## Non-Goals

- Claiming compatibility with every `RDAHELPER` version or option.
- Copying proprietary binaries, source, resources, or internal rule tables.
- Hiding several transformations behind one opaque task step.
- Using AI or probabilistic classification.

## Operation Model

Each RDA transformation is a normal structured operation with its own name,
parameters, explanation, preview, documentation, validation, compiler path,
and tests. Candidate behaviors—abbreviation expansion, 260/264 handling,
336/337/338 fields, configured GMD removal, relators, and templates—are
evaluated separately.

A behavior ships only when its open rule and Smith policy are explicit enough
to define deterministic input and output. Evaluation may conclude that a
candidate remains deferred; the ticket does not turn uncertainty into a
default.

## Smith RDA Cleanup Profile

The optional profile is an ordered preset of explicit operations and visible
parameters. Expanding the profile shows every child operation before it is
saved. The saved task contains those explicit operations or an equally
transparent versioned profile reference whose expansion is displayed and
fingerprinted; it never stores an opaque `RDAHELPER` equivalent.

Catalogers can remove, reorder, or configure individual operations. Preview
reports changes per operation.

## Content, Media, and Carrier Classification

The first supported profile component classifies records deterministically
from Leader, 006, and 007 values using a checked-in open mapping table. It
proposes exact 336, 337, and 338 fields.

Modes are:

- **Classify each record:** use the deterministic mapping;
- **Use one material type:** apply a cataloger-selected fixed mapping to every
  eligible record; or
- **Use explicit fields:** cataloger supplies the exact structured fields.

Existing valid fields are preserved by default and only missing fields are
added. Replacement or normalization requires an explicit nondefault action.
Ambiguous or conflicting classification skips the record and reports the
evidence; it never selects the nearest type.

## Other RDA Behaviors

- GMD removal requires an explicit field/subfield and exact or structured
  match; no blanket deletion default.
- 260/264 handling uses explicitly documented structural conditions and is
  unavailable where publication-function meaning cannot be inferred safely.
- Relator normalization uses a checked-in explicit source-to-target mapping
  with preserved unknown values.
- Abbreviation expansion uses a reviewed explicit mapping and exact token
  boundaries; it is not free-text rewriting.
- Configured templates reuse TASK-179 structured field templates.

These components may be delivered sequentially within TASK-181, but each must
pass its own review gate before joining the Smith profile.

## External Import Boundary

Imported `RDAHELPER` lines become unresolved Migration review cards under
TASK-185. A cataloger may replace one with the Smith profile or selected RDA
operations. The UI states that this is a chosen local workflow, not a proven
equivalent conversion.

## Failure Handling

Unknown mappings, ambiguous classification, malformed MARC, and conflicting
fixed fields skip and report rather than guess. Preview is non-mutating. No
partial output is adopted after an operation failure. Unknown external flags
remain blocking.

## Documentation and Testing

Each operation documents its rule authority, inputs, exact mapping, existing
field policy, skip/error behavior, and MARC before/after examples. Tests cover
every mapping cell, ambiguity, existing-field behavior, mixed files, fixed
override, explicit fields, profile expansion, round-trip, non-mutating preview,
and compiler/execution equivalence.

The complete mounted-source Docker suite and native compiler guard run where
applicable with every skip reported. Independent review must find no unresolved
Critical or Important issue.

## Rollout

This is application task-authoring work. It changes no production service,
route, proxy, authentication, worker topology, or ITS-managed configuration.
