# TASK-179 Structured Add Field and Build Field Authoring Design

**Ticket:** [TASK-179](../../../.tickets/TASK-179-structured-add-build-field-authoring.md)

**Parent:** [TASK-174](../../../.tickets/TASK-174-smith-metadata-studio-open-task-migration.md)

**Date:** 2026-07-30

**Status:** Approved

## Purpose

TASK-179 makes the existing task form usable for common Add Field and Build
Field work without requiring catalogers to author JSON or raw mnemonic
templates. It is the first authoring phase after TASK-178's native schema and
storage boundary.

The editor remains transparent. Structured controls are primary, but the
technical MARC mnemonic remains visible beside a plain-language explanation,
token annotations, and a deterministic preview. This lets new users complete
work safely while allowing catalogers to inspect exactly what will run.

The immediate acceptance examples come from sanitized versions of Smith CORE
Instance and Smith CORE Holdings and Items. They establish useful coverage
without claiming complete compatibility with MarcEdit or publishing the real
institutional task corpus.

## Goals

1. Replace Add Field's cataloger-facing JSON with repeatable, ordered subfield
   rows.
2. Replace normal Build Field raw templates with typed segments for literals
   and source control fields.
3. Make field construction understandable in plain language and inspectable in
   MARC mnemonic form.
4. Provide deterministic, non-mutating preview against the first loaded record
   when one is available.
5. Preserve existing form-task save, reopen, ordering, and execution behavior.
6. Convert only legacy Add and Build signatures whose meaning is exact.
7. Begin a checked-in supported-syntax reference that can later become in-app
   help.

## Non-goals

- Building a second task editor.
- Moving form-authored tasks to TASK-178's native-definition storage in this
  phase.
- Find/Replace and Subfield Edit improvements, which belong to
  [TASK-180](../../../.tickets/TASK-180-structured-find-replace-authoring.md).
- Recreating an opaque RDA Helper, which belongs to
  [TASK-181](../../../.tickets/TASK-181-explicit-rda-operations.md).
- Adding deterministic natural-language task drafting.
- Expanding or changing the existing AI feature.
- Implementing explicit field reordering, which belongs to
  [TASK-182](../../../.tickets/TASK-182-explicit-marc-field-reordering.md).
- Completing the full Smith CORE Instance or Smith CORE Holdings and Items
  workflows; later operation families are required.
- Guessing undocumented external task flags.
- Publishing real Smith vendor records or institutional task files.
- Deployment, service, routing, worker, cron, or ITS changes.

## Architecture and Storage Boundary

The existing ordered Tasks form remains the only editor. Its existing
operation-list state, `# OP:` serialization, form-task persistence, and
execution path remain authoritative for TASK-179.

TASK-178's native schema version 1 supports only `delete_tag`, `build_field`,
and `sort_fields`. The current form supports a wider mixed operation set.
Silently saving part of a form task as native JSON and part as legacy generated
code would create two incomplete sources of truth. TASK-179 therefore improves
the existing form-task path and does not introduce mixed native/legacy saves.
A later migration may move complete, supported operation sets across the
native boundary atomically.

The existing AI drafting paths remain available but frozen on their current
legacy Add/Build contract (`subfields` plus `if_absent`). TASK-179 does not
change their prompts, generators, accepted capability set, or validation
schema. Their output is normalized once, deterministically, when it enters the
structured form editor. Updating, expanding, disabling, or removing AI
drafting is deferred to a future release and requires a separate ticket.

The structured UI maps to existing operation values:

- Add Field stores an ordered list of subfield-code/value pairs.
- Build Field stores the existing typed `structured_subfields` representation.
- Form-only existing-field and missing-control actions use names distinct from
  native schema version 1. Native `existing_target`, native
  `missing_source`, and legacy `if_absent` are not treated as interchangeable.
- Operation ordering and move/duplicate/remove controls remain unchanged.
- Save/reopen must preserve every row and segment without normalization that
  changes meaning.

On open, exact legacy form values are normalized in memory into the structured
editor representation. A legacy `if_absent` value retains its actual
identical-field comparison semantics; it is not converted to tag-level skip.
Successfully converted Build Field values remove the stale raw `subfields`
copy so one operation never carries two competing representations. The
database is unchanged until the cataloger saves. If normalization cannot be
lossless, the original technical value remains visible with an actionable
error and the page continues rendering.

## Add Field Editor

An Add Field card contains:

- three-character numeric tag;
- indicator 1 and indicator 2, with a visible blank value;
- an ordered list of subfield rows;
- **Add subfield**, **Remove**, and reorder controls; and
- existing applicable advanced behavior shown with labeled controls.

Each subfield row contains a one-character subfield code and a literal value.
For example, an 877 is entered as:

| Tag | Indicator 1 | Indicator 2 | Code | Value |
| --- | --- | --- | --- | --- |
| 877 | blank | blank | m | Map |

The card shows:

```text
Add an 877 field with subfield m containing “Map”.
```

and:

```marc
=877  \\$mMap
```

JSON is not part of normal entry. Existing exact Add Field data is converted
to rows on reopen. Data that cannot be represented losslessly remains visible
in its prior technical form and blocks form save until the cataloger recreates
that operation with structured controls. This is distinct from an already
persisted unresolved import marker, which may be preserved unchanged while a
different operation is corrected.

## Build Field Editor

A Build Field card contains:

- target tag;
- target indicators when the target is a data field;
- ordered typed segments; and
- explicit behavior when the target already exists or source data is absent.

Supported segment types in this phase are:

1. **Literal text** — characters copied exactly.
2. **Source control field** — the value of a named control field such as 001 or
   003.
3. **Subfield** — a target subfield code whose value is composed from its own
   ordered literal and source-field pieces.

The user can add, remove, and reorder segments and subfields. Literal braces
remain literal data; they are not accidentally interpreted as source tokens.

The Smith CORE Instance example:

```marc
=035  9\$a({003}){001}
```

is presented as:

- create tag 035;
- set indicator 1 to `9`;
- leave indicator 2 blank;
- create subfield `a`;
- add literal `(`;
- insert the value of control field 003;
- add literal `)`;
- insert the value of control field 001.

Given:

```marc
=001  SYNTHETIC12345
=003  NhCcYBP
```

the preview is:

```marc
=035  9\$a(NhCcYBP)SYNTHETIC12345
```

The Smith CORE Holdings and Items example:

```marc
=876  \\$aB({003}){001}-SC$lInternet
```

is presented as:

- create tag 876 with blank indicators;
- create subfield `a`;
- add literal `B(`;
- insert 003;
- add literal `)`;
- insert 001;
- add literal `-SC`;
- create subfield `l` with literal value `Internet`.

Against the same source record, the preview is:

```marc
=876  \\$aB(NhCcYBP)SYNTHETIC12345-SC$lInternet
```

The technical mnemonic is displayed, not hidden. An adjacent link to the
syntax reference explains `=876`, `\\`, `$a`, `{003}`, `{001}`, and literal
text.

## Existing-Field and Missing-Source Behavior

The form uses explicit cataloger-facing choices for behavior that changes the
record:

- when the target tag exists, append another field, replace every field with
  that tag, or leave the record unchanged;
- legacy tasks may retain a fourth compatibility action that suppresses only
  an identical field, matching the existing `add_field_if_absent` helper; and
- when a required source control field is absent, skip building this field and
  report it in preview, or record a task error for that record.

No default silently deletes an existing field. The selected behavior appears
in the operation's plain-language summary, technical representation, and
preview. Replace/delete work occurs inside both the leader-condition and
source-availability guards, so a record is never stripped when the new field
will not be added.

These form actions are deliberately named `existing_field_action` and
`missing_control_action`. They do not reuse native version 1's
`existing_target: append|skip` or
`missing_source: skip_and_report` vocabulary. Native compilation remains
pinned to its existing `if_absent` bridge and compiler contract.

TASK-179 does not infer the meanings of the four trailing Boolean values in an
external `buildnewfield` line. An exact signature may be converted only after
its flags are mapped to proven behavior. Otherwise the imported instruction
remains visible, classified as unresolved, and blocked from execution.

## Preview

Preview is deterministic, read-only, and uses the same parsing and rendering
semantics as execution. It must not call a language model.

Each structured card shows:

1. a plain-language statement;
2. generated MARC mnemonic;
3. expandable token annotations; and
4. a resolved first-record example when a record is loaded.

Presentation validates before interpreting the operation. Invalid or
unconvertible legacy data shows its prior technical representation and an
actionable warning; summary, mnemonic, and annotation helpers never propagate
normalization errors into the Streamlit page. An unconvertible legacy
operation blocks form save until repaired.

If no record is loaded, the first three remain available and the resolved
example explains that a file is required. If a source tag is missing from the
first record, preview applies the selected skip/fail policy and names the
missing tag. Preview never mutates the selected source file or creates task
output.

## Validation and Failure Handling

Structured save and preview are blocked when:

- a tag is not exactly three numeric characters;
- an indicator is not one character or the explicit blank value;
- a subfield code is not one supported character;
- an Add Field has no subfield rows;
- a Build Field has no output segments;
- a source reference is not a supported control-field reference;
- structured data cannot round-trip through the existing form representation
  without loss;
- an Add Field or Build Field cannot be represented without an unresolved
  ambiguity; or
- generated mnemonic and structured values disagree.

Messages name the operation and faulty control and explain how to correct it.
Unsupported data is never silently dropped, normalized, or executed through a
best guess.

## Legacy Import Boundary

TASK-179 is not the general import-migration phase. It provides exact adapters
only for the Add Field and Build Field signatures required to reopen supported
form tasks and exercise the sanitized acceptance examples.

An external line is classified as:

- **exactly supported** — it can be represented and round-tripped without
  changing meaning;
- **recognized but unresolved** — its operation is known but one or more flags
  are not; or
- **unsupported** — no safe mapping exists.

Only exactly supported lines populate structured controls. Other lines retain
their local provenance and technical text in the migration review, but they
cannot be saved as an executable structured operation.

New imports containing any unresolved instruction are not persisted. Existing
saved tasks that already contain unresolved Add/Build instructions remain
openable and editable: an unchanged unresolved instruction may be preserved
while a cataloger corrects another operation. The unresolved instruction is
shown read-only with a warning. Submission performs a separate preflight and
refuses to queue that task until every unresolved Add/Build instruction has
been recreated with structured controls. General historical TODO comments
from unrelated operation families are not reclassified by TASK-179.
This preflight applies to submissions made after TASK-179 is deployed.
Operation payloads already queued before deployment are immutable snapshots
and are outside this gate.

## Syntax Reference

TASK-179 creates `docs/task-authoring-syntax.md` as a running reference for
behavior the application actually supports. It explains:

- MARC mnemonic tag, indicators, and subfield notation;
- literal text and source-field segments;
- structured Add Field and Build Field examples;
- existing-target and missing-source policies;
- the difference between a displayed technical mnemonic and stored structured
  values; and
- explicit unsupported or deferred constructs.

Examples are executable synthetic fixtures and are checked for drift. The
reference does not document guessed external syntax. It can later be adapted
into in-application help.

## Local MarcEdit Package Research

Read-only inspection of the user's installed `/Applications/MarcEdit.app`
helps classify external task text but is not an implementation dependency.
No proprietary binary, configuration content, UI resource, or documentation is
copied into the repository.

Findings are recorded by confidence:

### Confirmed from visible package labels and assembly metadata

- Build New Field exposes URL escaping, replace-existing, add-if-not-present,
  and always-add-new choices.
- Add/Delete, Edit Subfield, Find/Replace, Sort, Build New Field, and RDA Helper
  have distinct task parsers.
- RDA Helper is an external task instruction, not a MARC field.
- Visible RDA controls cover 040 `$e rda`, 502, qualifying information,
  GMD handling, abbreviation expansion, 260/264 evaluation, relators, and
  several RDA content/media/carrier and characteristic fields.

### Strong inference, not an accepted conversion rule

- The third Boolean in the observed Build New Field export likely corresponds
  to “add field if not present,” based on visible option order.
- Numeric values such as `100`, `101`, and `106` likely represent external
  bookkeeping or priority rather than MARC data.

### Unknown and therefore blocking

- Exact order and interaction of exported Build New Field Booleans.
- Pipe-delimited values such as `101|0` and `0|0`.
- Exact meaning of numeric option values.
- Sort Boolean meanings.
- Exact RDA transformation algorithms and defaults.

Unknowns remain unknown until proven by authoritative documentation or
controlled input/output evidence. They are not averaged into plausible
behavior.

## Deferred Deterministic Work

TASK-180 will add structured Find/Replace and Subfield Edit behavior, including
regex and explicit preservation of text before and after a match.

TASK-181 will replace an opaque imported RDAHELPER line with individually
reviewable operations. Its starting checklist is:

1. expand abbreviations;
2. evaluate 260/264;
3. add or normalize 336;
4. add or normalize 337/338;
5. handle GMD;
6. add relators; and
7. apply visible templates.

A later design may add a deterministic controlled-language drafting layer, for
example turning “remove every 856 and add one 856 with this URL” into a
structured draft while asking for missing indicators and subfield details.
That draft must use a grammar and deterministic validator, require cataloger
review, and never execute directly. Existing AI drafting remains unchanged as
a frozen compatibility path in TASK-179; any later AI redesign or retirement
requires its own ticket.

TASK-182 will provide explicit canonical MARC field reordering both as a quick
file action and as a reusable task step, commonly placed last. It will share
one stable ordering implementation while leaving View's source-order display
and TASK-169 warning intact.

## Corpus and Fixture Policy

Real institutional tasks remain local and untracked under `MarcEdit Tasks/`.
Real vendor records and local task text are not committed.

Committed tests use sanitized synthetic fixtures that retain only the operation
signatures required for behavior. Corpus-wide checks are a local supplement:

- if `MarcEdit Tasks/` is absent, the check reports an explicit skip stating
  that the institutional corpus is unavailable;
- if the directory exists but contains no readable task definitions, the check
  fails rather than passing vacuously; and
- its report classifies signatures without copying record content into tracked
  artifacts.

The committed suite's guarantees rest on synthetic fixtures, not on an
unavailable local corpus.

## Testing and Acceptance

### Smith CORE Instance

Synthetic coverage proves:

- structured construction of `035 9\ $a({003}){001}`;
- correct resolution of present 003 and 001 values;
- selected skip/fail behavior when either source field is absent;
- save/reopen with identical segment order and types; and
- an imported RDAHELPER line remains explicitly unsupported in TASK-179.

### Smith CORE Holdings and Items

Synthetic coverage proves:

- structured construction of
  `876 \\ $aB({003}){001}-SC$lInternet`;
- separate `$a` and `$l` subfields in the correct order;
- representative structured 852 and 877 Add Field definitions;
- explicit append, replace, or skip behavior for an existing target; and
- save/reopen without cataloger-authored JSON or raw template text.

### Automated checks

Intent-focused tests cover:

- subfield and segment add/remove/reorder behavior;
- `# OP:` serialization and exact reopen;
- literal brace preservation;
- source-control-field resolution;
- missing-source and existing-target policies;
- validation messages and blocking behavior;
- deterministic preview values;
- preview/execution agreement for blank indicators expressed as spaces or
  legacy backslashes;
- proof that preview does not mutate source records or create output;
- unchanged legacy AI-draft generation and deterministic normalization at
  editor handoff;
- exact legacy conversion;
- malformed and ambiguous import blocking;
- syntax-reference examples synchronized with executable fixtures; and
- Python 3.9 compatibility.

The focused suite and complete supported Docker suite must pass. Every skip is
reported with its reason; local-corpus absence is never described as passing
coverage.

### Cataloger Docker walkthrough

Using Docker, a reviewer:

1. opens the existing Tasks editor;
2. creates the structured 035 Build Field;
3. previews it against a synthetic record with 001 and 003;
4. saves, closes, and reopens it;
5. creates the structured 876 Build Field;
6. creates representative 852 and 877 Add Field operations without JSON;
7. verifies the plain-language, mnemonic, annotation, and resolved preview
   agree; and
8. confirms an ambiguous imported Build Field or RDAHELPER line is visible and
   blocked rather than guessed.

## Delivery Boundary

TASK-179 changes application code, tests, synthetic fixtures, and
documentation only. It does not require new services, environment variables,
systemd units, proxy routes, cron entries, database administration, or ITS
intervention. Production deployment remains a later coordinated action.
