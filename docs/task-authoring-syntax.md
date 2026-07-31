# Smith Metadata Studio Task Authoring Syntax

This reference documents the deterministic task operations supported by Smith
Metadata Studio. It explains the technical MARC representation shown beside
the structured editor. The editor stores typed values, not executable mnemonic
templates.

## Working with operation cards

The main task page shows each operation as a short, ordered summary instead of
expanding every form at once. Use **+ Add operation** or a card's **Edit**
action to open its focused editor.

The **Workspace** keeps setup controls beside preview results when an operation
supports preview, so you can adjust settings and inspect the MARC result
without changing tabs. Operations without preview use the full Workspace.
**Technical details** and **Reference** remain separate when relevant.

**Keep in task** retains the operation as a draft; it does not guarantee that
the task can be saved or run. A **Needs attention** card identifies the
numbered operation that must be corrected before saving or running. Canceling
a clean editor closes it directly. Canceling after changes asks for
confirmation and leaves the task unchanged if the edits are discarded.

Preview status belongs to the exact preview request and source record.
Reordering a card does not change what its preview means, and canceling a
draft does not replace the kept operation's preview status. The standalone
operation reference is read-only and lists operations alphabetically.

The cards and dialogs supplement the MARC syntax and technical examples in
this guide; they do not hide or replace them.

## What the structured editor stores

Add Field stores a target tag, two indicators, ordered subfield-code and
literal-value rows, an optional leader condition, and an existing-field
choice.

Build Field stores the same field information, but each subfield value is an
ordered sequence of:

- literal text; or
- a reference to control field 001 through 009.

The technical mnemonic is generated from these typed values so catalogers can
inspect exactly what the task will construct.

## MARC mnemonic anatomy

Consider:

```text
=876  \\$aB({003}){001}-SC$lInternet
```

- `=876` is the target MARC tag.
- `\\` means indicator 1 and indicator 2 are blank.
- `$a` starts subfield `a`.
- `B(`, `)`, and `-SC` are literal text.
- `{003}` inserts the value of control field 003.
- `{001}` inserts the value of control field 001.
- `$lInternet` creates subfield `l` with literal value `Internet`.

Backslashes are display notation for blank indicators; the structured editor
stores a blank indicator as a space.

## Add Field

Use Add Field when every subfield value is literal text. For example, tag 877,
blank indicators, code `m`, and value `Map` is displayed as:

```text
=877  \\$mMap
```

Subfields remain in the order shown in the editor. JSON is not required.

## Build Field

Use Build Field when a new field combines literal text with values already in
control fields. Each subfield contains its own ordered segments.

## Literal text

A literal segment is copied exactly. Braces entered in a structured literal
segment remain literal braces; they are not guessed to be source references.

## Source control fields

A source-control segment identifies one of 001 through 009. Preview resolves
it from the first loaded record. If a required source is absent, the selected
missing-control-field choice determines whether the field is skipped or the
record receives a task error.

## Existing-field choices

- **Add another field** appends the constructed field.
- **Replace every field with this tag** removes all fields with the target tag,
  then adds the constructed field.
- **Leave the record unchanged** skips construction when the target tag exists.
- **Add unless an identical field already exists** is a legacy compatibility
  behavior. It compares the indicators and complete ordered subfield values;
  a different field with the same tag does not suppress the new field.

These form choices use `existing_field_action`. Native task schema version 1
uses a separate `existing_target` vocabulary; the names are not
interchangeable.

## Missing-control-field choices

- **Do not build this field** skips construction and reports the missing
  control field in preview.
- **Record a task error for this record** fails that operation for the record.

These form choices use `missing_control_action`. Native task schema version 1
uses a separate `missing_source` vocabulary.

## Supported examples

### Build 035 from 003 and 001

```text
=035  9\$a({003}){001}
```

This creates 035 with indicator 1 `9`, blank indicator 2, and subfield `a`
composed from literal `(`, control field 003, literal `)`, and control field
001.

### Build 876 from literals, 003, and 001

```text
=876  \\$aB({003}){001}-SC$lInternet
```

This creates the two subfields described in the mnemonic-anatomy section.

### Add 852 and 877

The structured Add Field rows can represent examples such as:

```text
=852  8\$hOnline$tOther scheme$lSCINT
=877  \\$mMap
```

## Guided Find and Replace

The default changes only matched text. For example, finding `TFeba` in
035 subfield `a` and replacing it with `(SCTFEBA)` changes:

`TFeba9780020306634` → `(SCTFEBA)9780020306634`

Text before and after the match remains unless **Replace the whole selected
value** is chosen explicitly.

Targets in this release are control fields 001–009, one subfield code in one
tag, and all subfield values in one tag. Prepend and append act once per
selected value and do not use an empty Find.

For prepend and append, **Which selected values should change?** can apply the
action to every, the first, or the last selected value. First and last follow
the record's current MARC field and subfield order. This selected-value scope
is separate from first/every text-match occurrence within one value.

### Targets and actions

| Target | Matched text | Whole selected value | Prepend | Append |
| --- | --- | --- | --- | --- |
| Control-field value 001–009 | Supported | Supported | Supported | Supported |
| One subfield code in tag 010–999 | Supported | Supported | Supported | Supported |
| All subfield values in tag 010–999 | Supported | Supported | Supported | Supported |

For **All subfield values in a tag**, each subfield value in every occurrence
of the tag is selected independently. Values are not concatenated and MARC
mnemonic punctuation is not searched.

### Match modes and actions

| Match mode | Matched text | Whole selected value | Prepend | Append |
| --- | --- | --- | --- | --- |
| Contains | First or every match | Once when value matches | Not used | Not used |
| Starts with | First match only | Once when value matches | Not used | Not used |
| Ends with | First match only | Once when value matches | Not used | Not used |
| Whole value | First match only | Once when value matches | Not used | Not used |
| Raw regex | First or every match | Once using the first match | Not supported | Not supported |
| No match condition | Not supported | Not supported | Once per selected value | Once per selected value |

**First occurrence** and **Every occurrence** apply separately within each
selected value, not once across the record. Contains and raw-regex matched-text
replacement can therefore change the first match or every match in each
selected value. Starts-with, ends-with, and whole-value matching can produce
at most one match per selected value. Whole-selected-value replacement runs
once when a selected value matches. Prepend and append are literal and run
once per selected value unless first or last selected-value scope is chosen.

Raw regular expressions are available under the advanced control. They are
stored exactly with match mode `raw_regex`, validated before save, and must
receive a current sandbox preview before the task can be submitted. Raw-regex
whole-selected-value replacement expands capture references from the first
successful match.

Structural field, tag, indicator, tag-range, and structured-pattern behavior
is deferred to [TASK-184](../.tickets/TASK-184-structural-find-replace-authoring.md).
External conversion and compatibility-corpus behavior is deferred to
[TASK-185](../.tickets/TASK-185-external-find-replace-migration.md).

## Save, reopen, and preview

Saving preserves operation, subfield, and segment order. Reopening converts
only exact legacy Add/Build values. An unconvertible legacy value remains
visible and blocks form save until it is recreated.

Preview is deterministic, reads only the first loaded record, and does not
modify that record or create an output file.

## External task imports

External instructions are imported only when every line has an exact supported
meaning. Unknown flags, numeric options, and unsupported instructions are
listed for review and the task is not saved. Existing saved tasks containing
an unresolved Add/Build marker remain editable but cannot be submitted until
the marker is recreated with structured controls.

The existing AI drafting feature remains on its legacy contract. TASK-179 does
not change its prompts or capabilities; accepted output is normalized
deterministically when it enters the editor.

## Unsupported and deferred syntax

The following are not supported by the structured Add/Build editor:

- `RDAHELPER`;
- unproven trailing `buildnewfield` Boolean flags;
- arbitrary regular expressions over `.mrk` record text;
- undocumented numeric or pipe-delimited options; and
- unknown external task verbs.

Smith Metadata Studio does not guess these meanings. RDA transformations,
structural Find/Replace, external task conversion, and canonical MARC field
reordering are separate future task families.
