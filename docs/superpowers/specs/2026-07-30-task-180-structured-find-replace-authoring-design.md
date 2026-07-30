# TASK-180 Core Structured Find and Replace Authoring Design

**Ticket:** [TASK-180](../../../.tickets/TASK-180-structured-find-replace-authoring.md)

**Parent:** [TASK-174](../../../.tickets/TASK-174-smith-metadata-studio-open-task-migration.md)

**Depends on:** Completed
[TASK-179](../../../.tickets/TASK-179-structured-add-build-field-authoring.md)

**Follow-ups:**
[TASK-184](../../../.tickets/TASK-184-structural-find-replace-authoring.md)
and
[TASK-185](../../../.tickets/TASK-185-external-find-replace-migration.md)

**Date:** 2026-07-30

**Status:** Approved

## Purpose

TASK-180 adds a safe, cataloger-readable Find and Replace operation to the
existing Tasks form. It covers the common value-editing work needed now,
including the Smith 035 example, without asking a cataloger to write a regular
expression or Python.

The primary acceptance record contains:

```marc
=035  \\$aTFeba9780020306634
```

Replacing only the matched `TFeba` text with `(SCTFEBA)` must produce:

```marc
=035  \\$a(SCTFEBA)9780020306634
```

The identifier following the match is retained because new guided operations
default to replacing matched text, not the whole subfield value. Catalogers
who need a regular expression can always open an advanced raw-regex path.

## Scope Split

The original TASK-180 design combined seven target locations, six matching
modes, eight replacement actions, external conversion, legacy conversion, and
a Quick Find/Replace refactor. That cross-product did not define a complete
compatibility matrix and was too large for one safe implementation cycle.

The work is now divided as follows:

- **TASK-180:** control-field and subfield value changes, optional raw regex,
  preview, persistence, and empty-find safety.
- **TASK-184:** whole data fields, tags, indicators, tag ranges, structured
  pattern pieces, and named captures.
- **TASK-185:** exact external-instruction and legacy-operation conversion,
  including explicit meanings for empty-find instructions.

TASK-180 creates the deterministic engine that later tickets extend. It does
not add partial controls for TASK-184 or guess conversions assigned to
TASK-185.

## Goals

1. Add one `guided-find-replace` operation to the existing Tasks form.
2. Support one control-field value, one subfield code, or all subfield values
   in one tag.
3. Support contains, starts-with, ends-with, and whole-value matching through
   guided controls.
4. Keep raw regular expressions available as an advanced option.
5. Support matched-text replacement, whole-selected-value replacement,
   prepend, and append.
6. Make case handling and first/all occurrence behavior explicit.
7. Use the same deterministic transformation engine for preview and
   execution.
8. Preserve all existing saved operation semantics.
9. Fail closed on empty-find external imports and detectable saved generated
   empty-find operations.

## Non-goals

- Whole data-field replacement, tag changes, indicator changes, tag ranges,
  structured pattern pieces, or named captures; these belong to TASK-184.
- General external import translation or legacy-to-guided conversion; these
  belong to TASK-185.
- Interpreting `^b`, numeric external flags, arbitrary `.mrk` regex, or another
  undocumented external dialect.
- Refactoring Quick Find/Replace or adding **Add to saved task** there. Its
  existing in-process record selector and sandbox transformation remain
  unchanged.
- Reinterpreting or silently migrating `subfield-replace`,
  `replace-field-data-by-regex`, or
  `replace-field-subfield-and-indicators`.
- Adding the new operation to deterministic note drafting, Gemini drafting, or
  any other AI-assisted drafting contract.
- Changing TASK-178's native schema or compiler contract.
- Changing the database schema, task ownership, sharing, worker, deployment,
  service, cron, routing, or ITS configuration.
- General MARC field reordering, which belongs to
  [TASK-182](../../../.tickets/TASK-182-explicit-marc-field-reordering.md).
- The complete cataloger operation guide, which belongs to
  [TASK-183](../../../.tickets/TASK-183-cataloger-operation-reference.md).

## Storage and Compatibility Boundary

The existing ordered form-operation list, `# OP:` serialization, task
persistence, compiler, subprocess sandbox, and history remain authoritative.
TASK-180 does not introduce another task representation.

The new operation uses the form editor's flat parameter convention:

```json
{
  "kind": "guided-find-replace",
  "params": {
    "target_kind": "subfield",
    "tag": "035",
    "subfield": "a",
    "match_mode": "contains",
    "find": "TFeba",
    "ignore_case": false,
    "replacement_mode": "matched_text",
    "replacement": "(SCTFEBA)",
    "occurrences": "all",
    "condition": "always"
  }
}
```

Using `ignore_case` matches existing `subfield-replace` and
`BatchReplaceRequest` conventions and avoids an inverted compatibility
mapping.

Raw-regex mode stores the entered expression in `find` and its replacement in
`replacement` exactly, with `match_mode` set to the exact value `raw_regex`.
There is no separate `use_regex` Boolean. Generated expressions for
starts-with and ends-with are technical display values, not the canonical
saved intent.

Existing operation kinds retain their current code generation and execution
behavior. Opening an old task never changes its kind. TASK-180 does not offer
legacy conversion; TASK-185 owns that review and confirmation workflow.

## Cataloger Workflow

The card asks:

1. **Where should Smith Metadata Studio look?**
2. **What should it find?**
3. **What should it change?**

Normal controls appear first. **Write a regular expression directly** remains
available in an advanced expander.

### Where to Look

TASK-180 supports exactly three target kinds:

- **Control-field value** — one field from 001 through 009.
- **One subfield code** — one tag from 010 through 999 and one subfield code.
- **All subfield values in a tag** — every subfield value in each occurrence
  of one tag from 010 through 999.

The Leader (`000`) is not a control-field target. A control-field target cannot
specify a subfield. A data-field target requires a valid one-character
subfield code only when **One subfield code** is selected.

An existing supported Leader condition can wrap the operation. Matching and
mutation occur inside the same condition, so a false condition never changes
the record.

### What to Find

Guided match modes are:

- **Contains** — match the entered text anywhere in the selected value.
- **Starts with** — match only at the beginning.
- **Ends with** — match only at the end.
- **Whole value** — match only when the selected value equals the entered
  text.

Find text is required for matched-text and whole-selected-value replacement.
Empty Find is never overloaded to mean prepend, append, add-if-missing, or
ensure-one. Prepend and append are explicit replacement actions and therefore
do not show or store a Find value.

**Ignore uppercase/lowercase differences** maps to `ignore_case`. It defaults
to false.

### Advanced Raw Regular Expression

The advanced path:

- accepts a Python regular expression and replacement text;
- supports standard replacement references such as `\1`;
- preserves both strings exactly on save and reopen;
- validates expression syntax and capture references before save;
- states plainly that the expression is applied as written;
- allows a syntactically valid draft to be saved without a loaded file;
- requires a current successful sandbox preview before submission; and
- requires confirmation before switching modes when that would discard an
  entered raw expression.

Raw expressions are compiled and applied only inside the existing subprocess
sandbox. Raw regex is available for matched-text and
whole-selected-value replacement. Prepend and append do not need a match and
therefore do not expose raw regex. The current subprocess time limit remains
authoritative.

### What to Change

TASK-180 supports:

- **Replace only matched text** — preserves unmatched text before and after
  each match.
- **Replace the whole selected value** — replaces the complete control-field
  or individual subfield value after that value matches.
- **Add text before the selected value** — retains the selected value.
- **Add text after the selected value** — retains the selected value.

New operations default to **Replace only matched text**.

For matched-text replacement, **First occurrence** changes the first match in
each selected value and **Every occurrence** changes every match in each
selected value. Whole-selected-value replacement acts once per value that
matches. Prepend and append act once per selected value without a Find
condition. The occurrence control is disabled for all three because it cannot
change their result.

When **All subfield values in a tag** is selected, each subfield value is a
separate selected value. The operation does not concatenate subfields or
search MARC mnemonic punctuation.

## Compatibility Matrix

Every cell below is part of the TASK-180 contract. Combinations not listed are
unsupported in this ticket.

### Targets and actions

| Target | Matched text | Whole selected value | Prepend | Append |
| --- | --- | --- | --- | --- |
| Control-field value 001–009 | Supported | Supported | Supported | Supported |
| One subfield code in tag 010–999 | Supported | Supported | Supported | Supported |
| All subfield values in tag 010–999 | Supported | Supported | Supported | Supported |

For the final row, the chosen action applies independently to every subfield
value in every field occurrence with the selected tag.

### Match modes and actions

| Match mode | Matched text | Whole selected value | Prepend | Append |
| --- | --- | --- | --- | --- |
| Contains | First or every match | Once when value matches | Not used | Not used |
| Starts with | First match only | Once when value matches | Not used | Not used |
| Ends with | First match only | Once when value matches | Not used | Not used |
| Whole value | First match only | Once when value matches | Not used | Not used |
| Raw regex | First or every match | Once using the first match | Not supported | Not supported |
| No match condition | Not supported | Not supported | Once per selected value | Once per selected value |

Raw-regex whole-selected-value replacement expands capture references from the
first successful match. Prepend and append text is literal and is applied once;
this prevents one selected value from being prefixed or suffixed repeatedly.

Target choice never restricts match mode or occurrence behavior. The two
tables are independent projections of the supported target × match × action ×
occurrence space, so their valid rows and cells can be combined directly in
table-driven tests.

## Deterministic Engine and Compiler Integration

One pure engine owns request validation, matching, replacement, and structured
result metadata. It lives in a focused leaf library module that imports no
other `marcedit_web.lib` module. It does not read Streamlit session state,
write files, route work, or invoke a language model. In particular, it does
not import `is_control_tag` from `transforms`, because `transforms` re-exports
the engine entry point and that import would create a cycle.

`marcedit_web.lib.transforms` imports and re-exports the engine's public
record-transform entry point. The form compiler requests that transform name
through its existing `transforms_needed` mechanism. This matches the sandbox
contract, which pre-exposes public `transforms` attributes, and avoids adding a
new compiler special marker or a second implementation.

The engine reports:

- whether a record matched;
- whether it changed;
- selected-value and occurrence counts;
- condition-skipped status; and
- validation or execution errors.

The compiler emits one call with the saved explicit parameters. It does not
emit independent inline matching logic.

## AI Boundary

Adding a form-palette entry currently exposes an operation to two AI paths
unless it is excluded deliberately. TASK-180 keeps AI behavior unchanged by:

1. marking `guided-find-replace` unsupported in
   `ai_task_draft` before parameter validation;
2. making Gemini's prompt schema use that same support decision, so it does
   not advertise the operation; and
3. retaining focused regression tests for deterministic note drafts, AI draft
   validation, and Gemini prompt generation.

TASK-180 uses only existing palette parameter types (`text`, `select`, `bool`,
and the existing tag/subfield controls). It does not add an unchecked
`match_segments` type; structured segments belong to TASK-184.

## Explanation and Technical Transparency

Each valid card shows:

1. a plain-language summary;
2. its explicit saved choices;
3. generated technical matching information; and
4. a before/after preview.

The primary example says:

> In every 035 subfield a, replace every case-sensitive occurrence of
> “TFeba” with “(SCTFEBA)”. Keep text before and after each match.

It shows:

```text
Before: 035 $aTFeba9780020306634
After:  035 $a(SCTFEBA)9780020306634
```

Whole-selected-value replacement says that the complete value will be
discarded. When the operation can affect multiple selected values, the summary
and preview state how many previewed values will be discarded. Prepend and
append say that existing data is retained.

Technical details remain visible and link to `docs/task-authoring-syntax.md`.
TASK-180 adds the core operation syntax there; TASK-183 owns the complete
cataloger guide.

## Preview and Staleness

Preview is deterministic, non-mutating, and executes the same compiled engine
call used by saved tasks. Raw regex preview always runs inside the sandbox.

The preview state follows the existing `BatchReplacePreview` convention:

- `store_id` identifies the loaded store object;
- `store_revision` identifies its current content; and
- the normalized guided request stored with the preview must equal the
  operation's current normalized request.

A different store, changed revision, or changed request invalidates the
preview. TASK-180 does not introduce a separate compiler fingerprint for this
state.

The form reports match and change counts, condition skips, zero matches, and
representative before/after data. Preview never changes the loaded file,
saves a task, queues work, or promotes preview output as final output.

## Empty-Find Import Safety

The current `SUBFIELD_EDIT` importer emits:

```python
sf.value.replace(find, replacement)
```

Python treats an empty `find` specially: `"ab".replace("", "X")` produces
`"XaXbX"`. An empty-find external instruction can therefore become a silent
data corrupter.

TASK-180 changes this existing importer behavior deliberately:

- a newly imported empty-find `SUBFIELD_EDIT` is classified unresolved, shown
  with its original instruction, and not persisted as an executable task;
- a previously saved form operation whose `# OP:` marker identifies
  `subfield-replace` with an empty `find` remains visible but is blocked at
  submission; and
- unrelated existing operations and non-empty legacy replacements retain
  their current behavior.

The submission path uses one composed task preflight rather than adding
independent gates in `_submit_queued_run`. That preflight preserves
TASK-179's unresolved Add/Build check and adds the empty-find check. It parses
structured operation markers with `task_builder.parse_ops_from_source`; it
does not search generated Python source for text patterns.

Arbitrary code-mode tasks do not have a trustworthy structured marker and are
not reinterpreted by TASK-180. TASK-180 must not guess at Python source.
TASK-185 provides explicit add-if-missing, replace-existing, and ensure-one
conversion choices after their external meanings are reviewed.

The corpus value `^b` is not treated as proven prefix syntax. It remains
recognized but unresolved until documentation, executable behavior, or another
authoritative source establishes its exact meaning.

## Validation and Failure Handling

Save and preview validation block when:

- a tag is not exactly three numeric characters;
- the target and tag type conflict;
- a required subfield code is invalid;
- Find is empty for matched-text or whole-selected-value replacement;
- prepend or append carries a hidden Find or regex value;
- a match or replacement mode is unknown;
- a raw expression is invalid;
- a replacement refers to an undefined regex capture;
- a target/action combination is outside the compatibility matrix;
- the operation cannot round-trip without loss.

Saving a raw-regex draft does not require a loaded file or a successful
preview. Submission blocks when its raw-regex preview is missing or stale.
Submission also blocks detectable saved generated empty-find operations.
Messages identify the operation and control and explain how to correct it.
Unknown values fail closed. No path silently changes replacement scope,
drops entered data, or executes a guessed external meaning.

An invalid legacy operation remains visible in its existing technical form and
does not crash the Tasks page. Switching modes requires confirmation before
discarding raw pattern data.

## Testing Strategy

Tests encode cataloger intent, not only generated source strings.

### Characterization first

Before adding the new kind, tests pin current behavior for:

- literal and regex `subfield-replace`;
- `replace-field-data-by-regex`;
- `replace-field-subfield-and-indicators`;
- Quick Find/Replace match counts and transformations; and
- deterministic note, AI validation, and Gemini prompt paths.

These tests prove TASK-180 does not change the legacy or Quick workflows.

### Engine matrix

Table-driven tests cover every compatibility-matrix cell with:

- contains, starts-with, ends-with, whole-value, and raw-regex matching;
- case-sensitive and ignored-case behavior;
- first and every matched-text occurrence;
- one-time whole-value behavior and unconditional prepend and append behavior;
- control fields, one subfield code, all subfield values, repeated fields, and
  repeated subfields;
- no match and condition skip; and
- invalid combinations failing without mutation.

The primary regression asserts that `TFeba9780020306634` becomes
`(SCTFEBA)9780020306634`, not merely `(SCTFEBA)`.

Raw-regex tests include capture references, invalid expressions, invalid
references, first/all behavior, and subprocess timeout handling.

### Compiler, preview, and persistence

Tests prove:

- the compiler calls the re-exported transform entry point;
- preview and sandbox execution produce the same record;
- preview leaves source records and files unchanged;
- preview invalidates on store identity, store revision, or request change;
- raw regex cannot submit without a current successful preview;
- a valid raw-regex draft can save without a loaded source file;
- form values serialize and reopen exactly;
- summaries distinguish matched text, whole value, prepend, and append; and
- mode changes do not silently discard entered data.

### Import and compatibility safety

Tests prove:

- new empty-find `SUBFIELD_EDIT` input is unresolved and not saved;
- an existing marker-based empty-find form operation is visible but blocked
  from submission;
- non-empty legacy imports retain their current output;
- old operation kinds are never normalized into the new kind;
- `^b` remains unresolved rather than being guessed as prepend; and
- arbitrary code-mode tasks are not parsed or rewritten.

The untracked institutional corpus audit is a local-only, loudly reported
supplement. Committed guarantees use sanitized synthetic fixtures.

### Verification

Focused tests run through the supported Docker path before the complete Docker
suite. Every skip is reported. Python 3.9 compatibility is verified. The
TASK-178 native compiler contract manifest remains unchanged, verified by
`test_checked_in_contract_matches_every_golden_definition` and
`git diff --exit-code main -- marcedit_web/schemas/native-task-compiler-contract-v1.json`
from the implementation branch.

Browser acceptance covers:

- the primary 035 example;
- prepend and append;
- one control field and all subfields in a tag;
- raw-regex validation, preview gating, and staleness;
- save and reopen; and
- a visibly blocked empty-find import.

Evidence contains only synthetic records and task values. Independent review
must have no unresolved Critical or Important findings.

## Success Criteria

TASK-180 is complete when:

1. a cataloger can build the 035 `TFeba` replacement without regex or Python;
2. the result preserves the identifier following the match;
3. every supported target, match, action, and occurrence combination is
   defined by the compatibility matrix and tested;
4. matched-text replacement is the new-operation default;
5. optional raw regex remains available, round-trips exactly, validates
   before save, permits saving without a loaded file, and requires a current
   successful sandbox preview only at submission;
6. preview and execution call the same deterministic engine;
7. guided operations save and reopen without semantic loss;
8. existing operation, Quick Find/Replace, and AI behavior remain unchanged;
9. new and detectable saved empty-find operations fail loud instead of
   executing Python empty-string replacement;
10. TASK-184 and TASK-185 concerns are not partially implemented;
11. no native-schema, database, deployment, service, worker, cron, routing, or
    ITS change is introduced;
12. focused and complete Docker suites pass with every skip reported; and
13. independent review has no unresolved Critical or Important findings.
