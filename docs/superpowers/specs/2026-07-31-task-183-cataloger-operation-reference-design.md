# TASK-183 Cataloger Operation Reference Design

**Ticket:** [TASK-183](../../../.tickets/TASK-183-cataloger-operation-reference.md)

**Status:** Approved

## Purpose

The operation palette, in-app Reference surface, and Markdown guidance must not
drift. TASK-183 creates one deterministic documentation source that can serve
catalogers in the application and in a checked-in guide.

## Canonical Registry

A structured registry keyed by exact operation kind is the documentation
source of truth. Every entry contains:

- cataloger-facing purpose;
- when to use the operation;
- inputs, defaults, and allowed values;
- target, match, occurrence, and replacement scope;
- what surrounding data is preserved or discarded;
- existing-field, missing-data, invalid-data, and skip behavior;
- at least one MARC before/after example;
- transparent stored representation; and
- related operations.

The registry contains prose and structured examples only. It does not execute
code, route behavior, or infer documentation with a model.

## Generated Guide

A deterministic generator renders the registry into one checked-in Markdown
guide in cataloger-facing alphabetical order. Generation has stable headings,
field ordering, whitespace, and example formatting. The guide links to the
deeper task-authoring syntax document rather than removing technical details.

The generated file is reviewed and committed. Runtime application startup
does not generate or write documentation.

## In-App Reference

TASK-186's standalone Reference dialog and in-operation Reference tab read the
same registry. Search covers label, purpose, summary, inputs, and related
terms. The current operation opens directly to its entry; an unknown operation
shows its preserved technical identity and a clear unsupported message rather
than the entire unrelated palette.

Concise contextual help may quote the registry but must not create a second
manually maintained explanation.

## Freshness Contract

Tests fail when:

- a supported palette kind lacks exactly one registry entry;
- a registry key is not present in the palette;
- an entry omits a required section or example;
- a related-operation key is unknown;
- a stored example is structurally invalid; or
- regenerated Markdown differs byte-for-byte from the checked-in guide.

Palette labels and parameter definitions remain behavioral sources of truth.
Registry validation cross-checks documented inputs and allowed values against
them rather than duplicating executable validation.

## Authoring and Review Rules

Examples use sanitized synthetic MARC only. Each entry states deterministic
behavior without promising external-tool equivalence. Raw regex documentation
remains advanced and explicit about scope. RDA entries cite the open rule and
Smith policy recorded under TASK-181.

## Testing

Tests cover registry completeness, Markdown freshness, stable generation,
search, direct entry rendering, unknown operations, links, and representative
MARC examples. A cataloger acceptance pass reviews terminology and ambiguity;
automated tests cannot substitute for that language review.

Focused and complete mounted-source Docker suites report every skip.
Independent review must find no unresolved Critical or Important issue.

## Rollout

Documentation and application rendering only; no service, route, worker,
database, authentication, or ITS change.
