# TASK-190 Example-Task Import Completeness Design

**Ticket:** [TASK-190](../../../.tickets/TASK-190-smith-core-import-completeness.md)

**Depends on:** TASK-179, TASK-180, TASK-181, TASK-182, TASK-184, TASK-185,
and TASK-187

**Status:** Approved

## Purpose

The external-task importer currently rejects most instructions in the supplied
example corpus even when Smith Metadata Studio already has a deterministic
structured operation that can express the same cataloging intent. It then
places raw source lines, implementation reasons, and instruction fingerprints
in the primary interface. This is safe but not useful to a cataloger.

TASK-190 makes the local `MarcEdit Tasks/` corpus the initial compatibility
contract. Every instruction receives a deterministic automatic conversion or
an actionable suggestion card. A cataloger is never left with an unexplained
technical rejection or no next step.

## Corpus Boundary

The current local corpus contains 18 task documents, 109 unique instruction
lines, and these ten verbs:

- `ADD`
- `COPY`
- `DELETE`
- `EDITFIELD`
- `RDAHELPER`
- `REPLACE`
- `SORTBY`
- `SUBFIELD_EDIT`
- `SUBFIELD_REMOVE`
- `buildnewfield`

The real institutional task files remain untracked and local. Sanitized
synthetic fixtures cover every accepted signature and near miss in the
committed suite. A checked-in compatibility manifest records adapter IDs,
accepted shapes, evidence classifications, and fixture identifiers without
copying institutional task values or record content.

A local-only corpus audit reports every source document, instruction count,
adapter result, and remaining blocker. If the corpus is absent, the audit
skips loudly; the committed suite does not pass vacuously.

## Design Principles

1. Parse external instructions as data; never execute their text.
2. Preserve source order and expand one instruction to one or more adjacent
   structured operations when required.
3. Convert automatically only when the accepted signature and semantics are
   proven.
4. Treat a documented open Smith workflow as an explicit replacement when an
   external algorithm is proprietary. Label that replacement honestly.
5. Give every non-converted instruction a useful, prefilled next action.
6. Keep raw lines, fingerprints, adapter IDs, and evidence under Technical
   details rather than in the primary cataloger experience.
7. Saving a partial migration draft is allowed; preview and execution remain
   fail-closed until every blocking card is resolved.

## Architecture

### Parsed external instruction

The archive reader produces an ordered `ExternalInstruction` value with:

- verb;
- positional arguments;
- decoded option fields;
- source entry and line number;
- normalized instruction digest; and
- the original line for the local migration audit.

Parsing does not imply support. Malformed field counts, invalid Booleans,
unknown numeric options, and extra nonempty arguments remain explicit parse
errors.

### Evidence-backed adapter registry

The registry dispatches by verb and complete signature. Each adapter declares:

- accepted argument count and option values;
- the evidence supporting the interpretation;
- the structured operation or ordered operation expansion it produces;
- a cataloger-facing explanation;
- a safe suggestion factory for near misses; and
- sanitized equivalence fixtures.

Literal institutional values such as URLs, locations, and note text are
parameters, not adapter identities. The implementation must not create a
separate adapter for every corpus line.

### Structured suggestion card

An instruction that cannot convert automatically becomes a draft-only
`migration-blocker` card. It stores the parsed intent, reason, recommended
operation kind, safely prefillable parameters, source location, and digest.
The original instruction is retained for Technical details.

The compiler has no execution path for `migration-blocker`. Saving preserves
an inert structured marker, while preview, queued submission, direct task
execution, and export as a runnable task all reject a definition containing
one. Replacing the card with a normal operation removes the block.

This marker uses the existing task body/operation-marker storage path; TASK-190
does not require a database schema or service change.

## Compatibility Matrix

### DELETE

| External shape | Open representation | Result |
|---|---|---|
| Empty match, normal flags, exact tag | `delete-tag` | Automatic |
| Empty match, normal flags, `X` wildcard tag | `delete-tag` wildcard | Automatic |
| Plain field-value match | structured field-value deletion | Automatic after exact match-mode characterization |
| Indicator/subfield mnemonic match | structured field-signature deletion | Automatic after exact signature characterization |
| Duplicate-removal or other enabled Boolean | prefilled Delete suggestion naming the enabled policy | Blocking unless the policy is proven |

The adapter validates every trailing Boolean. It does not discard flags merely
because the common corpus examples set them to false.

### ADD

The installed task broker identifies the corpus option codes as distinct
paths: normal add (`100`), add when the tag is absent (`101`), conditional add
(`106`), and add when an identical field is absent (`108`). These become the
existing Add Field policies rather than opaque numeric settings.

| External shape | Open representation | Result |
|---|---|---|
| `100`, no condition | `add-field`, append | Automatic |
| `101`, no condition | `add-field`, skip if target tag exists | Automatic |
| `108`, no condition | `add-field`, skip if identical | Automatic |
| `106`, recognized Leader expression | `add-field` with named Leader condition | Automatic |
| `106`, unknown condition expression | prefilled Add Field suggestion with the condition explained | Blocking |

The recognized Leader conditions cover the corpus book, serial, integrating
resource/database, map, video, audio, score, and reviewed image signatures.
Delimiter variants such as `/.../`, `//...//`, and `///...///` normalize only
after the enclosed expression matches an accepted anchored signature.

### buildnewfield

The installed task broker maps the four trailing Booleans to `isEscaped`,
`ReplaceIfFound`, `ifNotPresent`, and `AlwayAdd`. The corpus uses two proven
policy combinations:

- `False, False, True, False`: build only when the target tag is absent;
- `False, False, False, True`: always build.

Templates parse into a target tag, two indicators, ordered subfields, and
typed segments. Segment types are:

- literal text;
- control-field value, such as `{001}` or `{003}`; and
- data-subfield value, such as `{035$a}`, `{050$b}`, or `{857$u}`.

All corpus Build Field templates use those forms and convert automatically.
Missing-source and repeated-source behavior is explicit in the open operation.
Functions, `[x]` multi-field tokens, malformed braces, and unrecognized flag
combinations become Build Field suggestion cards rather than partial
conversions.

### RDAHELPER

Local task-broker metadata establishes the 18 serialized positions. The
corpus signature enables only 336 and 337/338 generation; all other switches
are false and the language value is the unchanged sentinel.

Per the approved cataloger decision, that exact signature automatically
expands to the visible Smith RDA material-classification operation. The import
summary states that this is the transparent Smith open equivalent, not a claim
that the proprietary generation algorithm is byte-for-byte identical.
Unknown RDA flags produce a card recommending the closest explicit RDA
operations with each enabled external option translated into plain language.

### SUBFIELD_EDIT

| External shape | Open representation | Result |
|---|---|---|
| Nonempty literal Find, option `0|0` | guided matched-text replacement | Automatic |
| `^b`, option `0|0` | guided prepend | Automatic |
| `^e`, option `0|0` | guided append | Automatic |
| Empty Find, option `101|0` | add subfield only when missing | Automatic |
| Documented `^bTEXT` or `^eTEXT` | guided replace-plus-prepend/append expansion | Automatic only with equivalence fixtures |
| Other caret, move-pipe, or option shape | closest guided-operation suggestion | Blocking |

MarcEdit's published documentation explicitly defines `^b` as prepend and
`^e` as append. The installed editor path establishes option `101` as adding
the supplied subfield when no matching subfield was changed. Empty Find is
never passed to a generic string replacement.

### SUBFIELD_REMOVE

The corpus form removes a selected subfield only when its value matches the
provided text. It maps to the existing Delete Subfields Matching Value
operation after the `107|0` option behavior is characterized. A near miss
opens that operation prefilled but remains blocking.

### COPY

Unfiltered copies map to `copy-field`. The corpus also copies only fields whose
specified subfield matches a value, for example a source marker in `$3`.
TASK-190 extends Copy Field with an optional structured field predicate rather
than reproducing external filter strings. Source fields remain present, copied
fields preserve indicators and subfields, and the destination tag is explicit.

Unknown copy flags or filters become a prefilled Copy Field suggestion.

### EDITFIELD

The corpus contains a control-field edit. It maps to a dedicated structured
control-field value or character-position operation only after the exact
external argument meaning is characterized. Until then, the importer proposes
the closest control-field operation, explains the apparent value change, and
requires confirmation.

### REPLACE

External REPLACE operates over serialized mnemonic text and is never forwarded
to the native value-level raw-regex engine. Adapters recognize complete
signatures and translate them structurally:

- the proven 008 byte replacements become fixed-position control-field edits;
- exact complete-field normalizations become structured field-signature match
  plus complete-field replacement;
- exact tag changes become structural retag operations;
- the 856/956 staging sequence becomes a direct field predicate that preserves
  the original indicator condition and applies the URL edit only to eligible
  fields; and
- literal prefix removal from a constructed identifier becomes a structured
  matched-text operation on the identified field/subfield.

The operation model gains reusable field predicates for exact/wildcard
indicators, negative indicator matches, and subfield-value criteria. This
expresses the cataloging rule directly without exposing the temporary 956
implementation trick.

Any regex outside an accepted complete signature becomes a suggestion card.
The card may explain captures and propose a structured target, but never marks
the suggestion converted without cataloger confirmation.

### SORTBY

`SORTBY ALL True True` maps to `sort-fields`. Other scopes or flag combinations
produce a prefilled sorting suggestion and remain blocking.

## Cataloger Experience

### Fully converted task

After archive validation, a fully converted task opens directly in the normal
task editor. A compact banner says, for example:

> 18 instructions converted to editable Smith Metadata Studio operations.

It identifies any deliberate open replacement, such as the RDA conversion,
without showing raw instructions. The cataloger can inspect, reorder, preview,
save, or cancel the draft normally.

### Partially converted task

Converted operations and suggestion cards appear in original order. Each card
answers:

1. What does this instruction appear to do?
2. Why was it not converted automatically?
3. What structured operation is recommended?
4. What will be preserved or discarded?
5. What should the cataloger do next?

When parameters can be inferred safely, **Open suggested operation** replaces
the card with a prefilled operation dialog. The cataloger must confirm it.
**Choose another operation** opens the operation reference. **Technical
details** reveals the raw line, archive entry, line number, adapter decision,
and fingerprint.

The page shows bounded counts first: converted, needs confirmation, and cannot
yet be represented. Repeated identical blockers may be grouped visually but
remain distinct ordered cards in storage.

### Multiple tasks in one archive

Each archive entry becomes its own draft. Fully converted entries may be saved
independently. One blocked entry does not discard another valid entry. The
archive summary links directly to each draft and preserves TASK-187 diagnostics
across reruns.

## Validation and Failure Handling

- Adapter exceptions are contained to one instruction and become actionable
  blockers; they never silently drop the instruction.
- Malformed archives, unsafe paths, size limits, and quotas retain their
  existing archive-level rejection behavior.
- Unknown adapter IDs, option values, or compatibility-manifest versions fail
  closed.
- Reopening a saved partial draft preserves card order and suggestions.
- Compilation, preview, execution, runnable export, and background submission
  all share one blocker preflight.
- Adapter changes do not rewrite existing saved tasks automatically.
- A suggestion is visually and structurally distinct from a proven conversion.

## Documentation

The operation reference documents every new predicate, source reference,
control-field edit, copy filter, and replacement behavior with MARC before and
after examples. A separate migration guide lists supported external families
in cataloger language and explains why unknown patterns require confirmation.

The design records facts learned from official public documentation and
behavioral/metadata inspection of the locally installed package. It does not
copy, redistribute, or incorporate proprietary implementation code.

## Testing

Tests are layered:

1. parser tests for argument counts, flags, delimiters, malformed inputs, and
   provenance;
2. table-driven adapter tests for every compatibility-matrix row and near miss;
3. operation-level tests proving the structured output semantics;
4. adapter-versus-expected-MARC equivalence fixtures for every automatic
   conversion;
5. ordered archive tests for the sanitized versions of every example task;
6. UI tests for direct editable drafts, partial drafts, suggestion actions,
   collapsed technical details, rerun persistence, cancel, and reopen;
7. preflight tests proving no blocked draft can preview, run, submit, or export;
8. compatibility-manifest freshness tests; and
9. a loud local-only audit of all 18 current corpus documents.

No test may merely assert that an adapter name exists. Each automatic adapter
test must fail if its cataloging effect, preservation rule, occurrence policy,
or source ordering changes.

The complete mounted-source Docker suite, runtime-image disclosure run,
native-task compiler contract guard, and independent code review are required
before TASK-190 is Completed. Every skip is reported.

## Rollout

TASK-190 changes application code, documentation, sanitized fixtures, and
tests only. It does not change the production directory, systemd unit, proxy,
OAuth configuration, database schema, worker topology, or ITS-managed startup
configuration. If implementation discovers that one of those changes is
necessary, work stops and the design returns for approval rather than silently
expanding deployment scope.
