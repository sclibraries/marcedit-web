# External task migration review

Smith Metadata Studio imports external task text through a fail-closed review
boundary. Each source line keeps its original text and SHA-256 instruction
fingerprint; source order is preserved.

## Converted

`SUBFIELD_EDIT` with a nonempty literal Find value and a one-character
subfield code converts to the guided operation. It is case-sensitive,
replaces all matched text, and preserves text before and after each match.

Exact `^b` and `^e` Find values convert to guided prepend and append actions.
The value after the caret is retained; arbitrary caret syntax remains a
confirmation item. An `ADD` line with a proven option (`100`, `101`, `106`, or
`108`) becomes **Add field** with its append, skip-if-tag, skip-if-identical,
or reviewed Leader condition. A `buildnewfield` line with a proven flag
combination becomes **Build field from template** with explicit control-field
references.

`DELETE` with an exact tag, `X` wildcard tag, reviewed value match, or reviewed
mnemonic signature becomes a structured delete operation. `COPY` becomes
**Copy field**, including the reviewed subfield predicate; the source remains
in the record. `SUBFIELD_REMOVE` with the reviewed `107|0` option becomes
**Delete subfield when value matches**.

The reviewed `RDAHELPER` Smith signature becomes the visible Smith RDA material
classification profile. This is an open deterministic equivalent for the
documented Smith workflow, not a claim that proprietary MarcEdit code is being
reimplemented. The reviewed `REPLACE` signatures become fixed-position 008
edits, structured field changes, or predicate-aware 856/956 transformations.

The two proven 008 form-of-item `REPLACE` signatures convert to **Set 008
form-of-item** with their original fixed position: byte 23 for the `{25}`
signature and byte 29 for the `{31}` signature. The conversion does not
reselect a position from each record's Leader, so mixed-type batches retain
the external instruction's position-fixed meaning. A `SORTBY` line whose
scope is `ALL` converts to **Sort fields by tag**; other sort flags remain
blocking until their meaning is proven.

## Choice required

An empty Find value is never executed as Python `str.replace('', value)`. The
cataloger must choose one explicit meaning: `add_if_missing`,
`replace_existing`, or `ensure_one`. Once selected, the instruction becomes
the explicit **Imported empty-find subfield policy** operation; the review
card opens that operation in the normal task editor. Without a selection it
remains blocked.

## Unresolved

Unreviewed caret syntax, arbitrary regex over MarcEdit's `.mrk` text,
undocumented numeric flags, unknown `RDAHELPER` switches, uncharacterized
`EDITFIELD` modes, and unknown verbs remain visible and blocking. The importer
never claims compatibility with undocumented external behavior.

## What to do next

Every blocking card is retained in source order and includes the apparent
cataloging intent, the reason automatic conversion is unsafe, and the closest
structured operation. When its parameters are safe to infer, **Open suggested
operation** opens a prefilled editor. Review the values, keep the replacement,
or cancel to retain the blocker. A task containing unresolved cards may be
saved as a draft, but preview, execution, export, and background submission
remain blocked until each card is replaced or removed.

The import summary shows converted and confirmation-required counts first.
Source lines, fingerprints, adapter evidence, and deliberate open-equivalent
disclosures are available under **Technical details**.

## Family guide

| Source family | Automatic conversion | Confirmation required |
| --- | --- | --- |
| `ADD` | Proven option and reviewed Leader condition | Unknown option or condition |
| `buildnewfield` | Control references and reviewed flags | Functions, multi-field tokens, or unknown flags |
| `DELETE` | Exact/wildcard tags and reviewed signatures | Unproven duplicate/filter flags |
| `COPY` | Unfiltered or reviewed subfield predicate | Unknown filters or flags |
| `SUBFIELD_EDIT` | Literal replacement, `^b`, `^e`, and reviewed empty-find policy | Other caret, move-pipe, or option syntax |
| `SUBFIELD_REMOVE` | Reviewed exact-value removal | Other option or matching semantics |
| `REPLACE` | Complete reviewed signatures only | Arbitrary `.mrk` regex |
| `RDAHELPER` | Exact Smith open profile | Any other switch combination |
| `SORTBY` | `ALL True True` | Other scopes or flags |
| `EDITFIELD` | Only characterized signatures | Unproven field/mode combinations |
