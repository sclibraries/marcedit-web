# TASK-180 Structured Find and Replace Authoring Design

**Ticket:** [TASK-180](../../../.tickets/TASK-180-structured-find-replace-authoring.md)

**Parent:** [TASK-174](../../../.tickets/TASK-174-smith-metadata-studio-open-task-migration.md)

**Date:** 2026-07-30

**Status:** Approved

## Purpose

TASK-180 makes common MARC find-and-replace work understandable and safe in
the existing Tasks form. A cataloger describes where to look, what to match,
and what to change through labeled controls. The editor then shows the
plain-language meaning, technical expression, and a deterministic preview
before execution.

The primary acceptance example is a 035 subfield whose value begins with
`TFeba` followed by an identifier. Replacing only the matched `TFeba` text
with `(SCTFEBA)` must retain the identifier:

```marc
=035  \\$aTFeba9780020306634
```

becomes:

```marc
=035  \\$a(SCTFEBA)9780020306634
```

The design generalizes that example without requiring regular expressions for
normal work. Catalogers who need them retain an explicit advanced raw-regex
path.

## Goals

1. Add one guided Find and Replace operation to the existing Tasks form.
2. Make replacement scope explicit, especially the difference between
   replacing matched text, an entire subfield value, or an entire field.
3. Support literal contains, starts-with, ends-with, and whole-value matching
   without requiring regular expressions.
4. Support structured patterns that combine literals, variable text, digits,
   character sets, and anchors.
5. Keep raw regular expressions available as an advanced option with
   validation, exact preservation, and successful-preview gating.
6. Use one deterministic matching and replacement engine for preview and
   execution.
7. Preserve the behavior of existing saved operations.
8. Convert only external or legacy instructions whose meaning is known
   exactly.

## Non-goals

- Creating a second Tasks editor.
- Reinterpreting or silently migrating existing saved `subfield-replace`,
  `replace-field-data-by-regex`, or
  `replace-field-subfield-and-indicators` operations.
- Completing general MarcEdit task compatibility.
- Guessing the meaning of undocumented external flags or regex dialects.
- Asking a language model to interpret, route, compile, validate, or execute
  task instructions.
- Changing the existing AI task-draft behavior, prompts, palette contract, or
  validation. That work is explicitly deferred to a later release.
- Changing TASK-178's native-task schema or compiler contract.
- Changing the database schema, task ownership, task sharing, worker,
  deployment, service, cron, routing, or ITS configuration.
- Adding an **Add to saved task** action to Quick Find/Replace. The Quick tool
  shares the deterministic engine where its existing behavior is equivalent,
  but that authoring shortcut is deferred.
- Implementing general MARC field reordering, which belongs to
  [TASK-182](../../../.tickets/TASK-182-explicit-marc-field-reordering.md).
- Writing the complete cataloger help guide, which belongs to
  [TASK-183](../../../.tickets/TASK-183-cataloger-operation-reference.md).

## Chosen Approach

TASK-180 adds a new `guided-find-replace` form operation. It stores structured
cataloger intent and compiles through the existing deterministic form-task
pipeline. It does not alter the meaning of existing operation kinds.

This approach was selected over:

1. changing `subfield-replace` in place, which would change existing task
   behavior;
2. adding a separate operation for every combination of location, matching,
   and replacement behavior, which would make the palette difficult to learn;
   and
3. storing only generated regular expressions, which would hide the
   cataloger's intent and make safe editing and explanation harder.

One guided operation provides a consistent card while progressive disclosure
shows only controls relevant to the selected behavior.

## Storage and Compatibility Boundary

The existing ordered form-operation list, `# OP:` serialization, task
persistence, compiler, subprocess sandbox, and execution history remain
authoritative.

A new guided operation stores its intent directly using the form editor's
existing flat parameter convention. It does not store a generated regular
expression as the canonical value. A representative value is:

```json
{
  "kind": "guided-find-replace",
  "params": {
    "target_kind": "subfield",
    "tag": "035",
    "subfield": "a",
    "match_mode": "contains",
    "find": "TFeba",
    "case_sensitive": true,
    "replacement_mode": "matched_text",
    "replacement": "(SCTFEBA)",
    "occurrences": "all",
    "condition": "always"
  }
}
```

Structured patterns add an ordered `match_segments` list. Raw-regex mode stores
the entered pattern in `find` and its replacement in `replacement` exactly.
The saved values must retain every explicit concept and round-trip without
semantic loss.

Existing saved operation kinds retain their current semantics:

- existing `subfield-replace` operations continue to use their present
  literal or regex substitution behavior;
- existing `replace-field-subfield-and-indicators` operations continue to
  replace the complete selected subfield value when they currently do so; and
- existing raw field-regex operations remain raw operations.

Opening an old task does not silently convert it. When a known legacy
operation can be represented losslessly, the editor offers an explicit
**Convert to guided operation** action. Conversion requires cataloger
confirmation and must preserve a comparison of old and proposed meanings.
An operation that cannot be converted exactly remains in its current
technical form.

## Cataloger Workflow

The operation card begins with three questions:

1. **Where should Smith Metadata Studio look?**
2. **What should it find?**
3. **What should it change?**

The normal path uses guided controls. Advanced controls remain collapsed until
the cataloger requests them.

### Where to Look

Supported locations are:

- a complete control-field value;
- a specific subfield code within a data-field tag;
- every subfield value within one data-field tag;
- indicator 1 or indicator 2;
- the field tag itself; and
- an explicitly selected inclusive tag range where the chosen target type is
  valid.

The UI prevents incompatible combinations. For example, a control-field
target cannot also specify indicators or a subfield code. A range cannot mix
control- and data-field behavior when the requested action would be
ambiguous.

The operation can also use an existing supported Leader condition. The
condition wraps matching and mutation together; no record is changed when the
condition is false.

### What to Find

The default match modes are:

- **Contains** — find the entered text anywhere in the selected value.
- **Starts with** — find it only at the beginning.
- **Ends with** — find it only at the end.
- **Whole value** — change only a value that equals the entered text.
- **Structured pattern** — combine guided pattern pieces.

All modes expose an explicit case-sensitive choice. Find text cannot be empty.
Prepending and appending are modeled as replacement actions rather than as an
empty find.

Structured patterns support ordered pieces:

- literal text;
- any text;
- one or more digits;
- a cataloger-entered character set;
- start of value; and
- end of value.

Where later replacement needs the matched value, a piece can be given a
plain-language name. The replacement editor refers to that name instead of
asking the cataloger to count regex groups. The generated expression is shown
as technical information, but it is not the canonical saved intent.

### Advanced Raw Regular Expression

An advanced expander provides **Write a regular expression directly**.

When selected:

- the cataloger enters the raw expression and replacement text;
- standard Python replacement references such as `\1` are supported;
- the expression and replacement are preserved exactly on save and reopen;
- the selected replacement scope remains explicit;
- invalid expressions and invalid capture references block save;
- a plain warning states that the expression is applied as written;
- a successful representative preview is required before submission; and
- changing back to guided mode requires confirmation before discarding the
  raw expression.

Preview and execution retain the existing subprocess time limit. TASK-180
does not claim that arbitrary regular expressions are safe to execute in the
Streamlit process.

### What to Change

Replacement actions are:

- **Replace only the matched text**;
- **Replace the whole subfield value**;
- **Replace the whole field**;
- **Add text before the selected value**;
- **Add text after the selected value**;
- **Change the field tag**;
- **Set indicator 1**; and
- **Set indicator 2**.

Only compatible actions appear for the selected target.

For a data field, **Replace the whole field** is selected after a match in a
specific subfield or any subfield identifies the field. Its replacement is
entered with TASK-179's structured indicators-and-subfields controls. The
operation never treats MARC mnemonic punctuation such as `$a` as ordinary
replaceable text. For a control field, whole-field replacement means replacing
its complete data value.

New guided text replacements default to **Replace only the matched text**.
This explicitly preserves text before and after the match. Whole-subfield and
whole-field replacement require deliberate selection and are named in the
summary and preview.

The cataloger chooses whether to change the first occurrence in each selected
value or every occurrence. When multiple fields or subfields meet the
criteria, the operation applies consistently to each selected value; it does
not stop after the first record-level match.

## Deterministic Matching and Replacement Engine

One pure deterministic engine owns validation, matching, replacement, and
cataloger-readable result metadata. It accepts a normalized guided request and
a MARC record or field value. It does not read Streamlit session state, write
files, invoke a language model, or decide task routing.

The engine returns enough structured information for callers to report:

- whether the record matched;
- whether the record changed;
- how many values and occurrences matched;
- which configured condition caused a skip; and
- validation or execution errors.

The saved-task compiler emits a small call into this engine. It does not
duplicate matching logic as generated inline Python.

The card-level preview uses the same request normalization and engine. The
existing Quick Find/Replace path should use this engine where its current
literal and regex behavior is semantically equivalent. Adopting the shared
engine must not broaden or silently change Quick Find/Replace behavior.

The compiler and sandbox remain the execution boundary. Regular expressions
are compiled and applied inside task execution, not during ordinary
Streamlit-page rendering. A lightweight syntax and capture-reference check
occurs before save, but successful execution preview remains mandatory for raw
regex.

## Explanation and Technical Transparency

Every valid guided operation shows four aligned representations:

1. a plain-language summary;
2. the saved structured choices;
3. generated technical matching information, including regex when one is
   used internally; and
4. a before/after preview.

For the primary example, the summary is equivalent to:

> In every 035 subfield a, replace every case-sensitive occurrence of
> “TFeba” with “(SCTFEBA)”. Keep text before and after each match.

The preview must show:

```text
Before: 035 $aTFeba9780020306634
After:  035 $a(SCTFEBA)9780020306634
```

Whole-value replacement must instead say that the entire selected value will
be discarded and replaced. Prepend and append summaries state that existing
data is retained.

Technical details are not hidden. The operation links to
`docs/task-authoring-syntax.md`, and TASK-180 adds the supported find/replace
syntax there. Complete operation guidance remains assigned to TASK-183.

## Preview

Preview is deterministic and non-mutating. It runs through the same normalized
request and transformation engine used by execution.

The Tasks form provides:

- a first-record or representative-record before/after example when a file is
  loaded;
- match and change counts for the previewed sample;
- the number of records skipped by conditions;
- a clear zero-match result; and
- validation or execution errors associated with the specific operation.

Raw regex preview must execute inside the existing sandbox boundary. The UI
records a preview fingerprint derived from the operation's exact saved
parameters and the source revision. Any relevant edit or source-file change
invalidates the successful-preview state.

Preview never changes the loaded file, saves a task, queues durable work, or
creates a task output. Submission and full execution perform their normal
fresh run; preview output is not promoted as final output.

## Import and Conversion Boundary

External instructions are classified as exactly supported, recognized but
unresolved, or unsupported.

Known exact examples include:

- `SUBFIELD_EDIT 856 u ^b <prefix>` as prepend `<prefix>` to 856 subfield u;
- an exact field retag expression such as changing `=956  ` to `=856  ` when
  the external syntax and spacing have a proven meaning; and
- exact literal or proven-regex subfield replacement signatures whose
  occurrence, case, and replacement scopes are all known.

An empty-find external subfield edit is not assumed to mean one thing. The
cataloger must choose among:

- add the subfield when it is missing;
- replace existing occurrences; or
- ensure exactly one occurrence.

Those behaviors are not treated as equivalent.

Arbitrary regular expressions over `.mrk` text remain blocking unless an
adapter proves the target, match, replacement, and occurrence semantics.
External regex syntax is not assumed to be Python-compatible. A proven subset
converts; otherwise the original instruction and reason remain visible for
cataloger review.

Conversion never deletes the original review evidence silently. A proposed
guided operation shows its interpreted meaning and requires confirmation.

## Validation and Failure Handling

Save and preview are blocked when:

- a tag or tag range is invalid;
- a selected target is incompatible with the tag type;
- a subfield code is invalid;
- an indicator value is not one character or the explicit blank value;
- Find is empty for an action that requires a match;
- a character set or structured pattern piece is invalid;
- a raw regular expression is invalid;
- a replacement refers to a capture that the expression does not define;
- a replacement action conflicts with its selected target;
- a tag change would create an invalid MARC field;
- the operation cannot round-trip through its saved representation;
- an imported instruction has unresolved semantics; or
- a required raw-regex preview is missing or stale.

Validation names the operation and faulty control and explains how to correct
it. Unknown modes and values fail closed. Data is not silently discarded,
coerced into a different replacement scope, or executed using a best guess.

If a mode switch would discard entered pattern data, the UI requires explicit
confirmation. An invalid legacy operation remains visible in its existing
technical form and does not crash the Tasks page.

## Testing Strategy

Tests encode cataloger intent rather than merely asserting generated strings.

### Engine tests

Table-driven tests cover:

- contains, starts-with, ends-with, whole-value, structured, and raw-regex
  matching;
- case-sensitive and case-insensitive behavior;
- first and every occurrence;
- matched-text, whole-subfield, whole-field, prepend, and append behavior;
- preservation of text before and after a match;
- named structured captures and raw `\1` replacement references;
- control fields, selected subfields, all subfields, structured whole-field
  replacement, indicators, tags, and valid tag ranges;
- repeated fields and repeated subfields;
- no-match and condition-skipped records; and
- invalid combinations failing without mutation.

The primary regression asserts that replacing `TFeba` in
`TFeba9780020306634` produces `(SCTFEBA)9780020306634`, not merely
`(SCTFEBA)`.

### Preview and compiler tests

Tests prove:

- preview and sandbox execution produce the same transformed record;
- preview leaves the source record and source file unchanged;
- compiled saved tasks call the shared engine rather than a second
  implementation;
- raw regex preview is sandboxed and becomes stale after an operation or
  source revision change;
- zero matches and skipped conditions are reported; and
- invalid regex and capture references never reach execution.

### Editor and persistence tests

Tests prove:

- guided controls serialize and reopen losslessly;
- progressive controls do not discard hidden values;
- switching away from raw regex requires confirmation;
- summaries distinguish matched-text, whole-value, prepend, and append;
- technical regex is visible when generated or entered;
- nested widget keys remain unique; and
- invalid legacy data remains visible without taking down the page.

### Compatibility and import tests

Characterization tests pin existing saved operation behavior before the new
operation is added. Tests also prove:

- old operation kinds are not normalized into the new kind automatically;
- an explicit conversion is lossless before it is offered;
- supported external signatures map to the intended guided definition;
- ambiguous empty-find and arbitrary `.mrk` regex instructions remain
  blocking; and
- the untracked institutional corpus audit is a local-only, loudly reported
  supplement rather than a CI guarantee.

The existing AI draft tests remain unchanged and must continue passing.
TASK-180 does not add the new operation to the AI palette.

### Verification

Focused tests run first through the supported Docker path, followed by the
complete Docker suite. Every skip is reported. Python 3.9 compatibility is
verified. The TASK-178 native compiler contract manifest must remain unchanged
unless an independently justified native-schema ticket changes it.

Browser acceptance covers the primary 035 example, a prepend example, raw
regex validation and preview gating, save/reopen, and a visibly blocked
ambiguous import. Evidence contains only synthetic records and task values.

Independent review must have no unresolved Critical or Important findings
before TASK-180 is marked Completed.

## Success Criteria

TASK-180 is complete when:

1. a cataloger can build the primary 035 replacement without writing regex or
   Python;
2. the result preserves the identifier following `TFeba`;
3. replacement scope is explicit in controls, summary, and preview;
4. guided matching covers literal, anchored, structured, and optional raw
   regex workflows;
5. raw regex remains available, round-trips exactly, validates before save,
   and requires a current successful preview;
6. preview and execution use the same deterministic transformation logic;
7. saved guided operations reopen without semantic loss;
8. existing saved operations retain their established behavior;
9. only exact external translations convert and ambiguous instructions fail
   loud;
10. no AI, native-schema, database, deployment, service, worker, cron,
    routing, or ITS change is introduced;
11. focused and complete supported Docker suites pass with every skip
    reported; and
12. independent review has no unresolved Critical or Important findings.
