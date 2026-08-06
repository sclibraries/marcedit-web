# Task operation reference

This guide is generated from the checked-in deterministic operation registry.

## Add field

**Operation kind:** `add-field`

**Purpose:** Add one explicitly described MARC field.

**When to use:** Use when the indicators and subfields are known and no source-field template is needed.

**Inputs:** `tag`, `ind1`, `ind2`, `subfields`, `condition`, `if_absent`

**Behavior:** Appends the field or follows the selected existing-field policy.

**Preserves:** All existing fields and their source order are preserved unless replace-all is selected.

**Skip behavior:** A field is skipped only under the selected skip policy.

**Error behavior:** Invalid tags, indicators, or subfields block saving.

**Before:** `(no 877 field)`

**After:** `877 $m Map`

**Stored representation:** Tag, indicators, structured subfields, condition, and existing-field policy.

**Related:** `build-field`

## Add subfield to existing fields

**Operation kind:** `add-subfield`

**Purpose:** Append (or prepend) a subfield to every variable field with the given tag. Control fields (00X) are skipped.

**When to use:** Use add subfield to existing fields when that specific MARC change is required.

**Inputs:** `tag`, `code`, `value`, `position`

**Behavior:** Append (or prepend) a subfield to every variable field with the given tag. Control fields (00X) are skipped.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `856 $u https://example.org`

**After:** `856 $u https://example.org $y Smith: Link`

**Stored representation:** Structured `add-subfield` parameters validated by the task form.

**Related:** none

## Apply institution mapping profile

**Operation kind:** `institution-profile`

**Purpose:** Create editable institution-specific fields from selected source fields.

**When to use:** Use apply institution mapping profile when that specific MARC change is required.

**Inputs:** `source_tag`, `rows`, `occurrence`, `max_fields_per_record`, `max_fields_per_batch`

**Behavior:** Create editable institution-specific fields from selected source fields.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `MARC field before operation`

**After:** `MARC field after operation`

**Stored representation:** Structured `institution-profile` parameters validated by the task form.

**Related:** none

## Build field from template

**Operation kind:** `build-field`

**Purpose:** Build a field from literal text and explicit control-field references.

**When to use:** Use when a new value contains data copied from fields such as 001 or 003.

**Inputs:** `tag`, `ind1`, `ind2`, `subfields`, `condition`, `if_absent`

**Behavior:** Resolves each typed control-field segment and creates the requested field.

**Preserves:** Literal text and existing record fields are preserved according to the field policy.

**Skip behavior:** Missing control data follows the selected skip or fail policy.

**Error behavior:** Malformed segments or unsupported control references block saving.

**Before:** `001 $a abc123`

**After:** `876 $a Babc123-SC`

**Stored representation:** Typed text/control-field segments, never generated executable template text.

**Related:** `add-field`

## Build fields from matching source fields

**Operation kind:** `build-fields-from-source`

**Purpose:** Create destination fields from explicit source-field templates.

**When to use:** Use build fields from matching source fields when that specific MARC change is required.

**Inputs:** `source_tag`, `destination_tag`, `indicators`, `subfield_templates`, `occurrence`, `missing_source_action`, `existing_field_action`, `predicate`, `max_fields_per_record`, `max_fields_per_batch`

**Behavior:** Create destination fields from explicit source-field templates.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `MARC field before operation`

**After:** `MARC field after operation`

**Stored representation:** Structured `build-fields-from-source` parameters validated by the task form.

**Related:** none

## Copy field

**Operation kind:** `copy-field`

**Purpose:** Duplicate every field with the source tag as a new field with the destination tag. The original stays in place.

**When to use:** Use copy field when that specific MARC change is required.

**Inputs:** `src_tag`, `dst_tag`, `predicate`

**Behavior:** Duplicate every field with the source tag as a new field with the destination tag. The original stays in place.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `245 $a Title`

**After:** `245 $a Title
246 $a Title`

**Stored representation:** Structured `copy-field` parameters validated by the task form.

**Related:** none

## Copy fields with occurrence policy

**Operation kind:** `copy-fields-with-policy`

**Purpose:** Copy selected source fields while choosing first, last, or all occurrences and an explicit destination collision policy.

**When to use:** Use copy fields with occurrence policy when that specific MARC change is required.

**Inputs:** `source_tag`, `destination_tag`, `occurrence`, `existing_field_action`, `predicate`, `max_fields_per_record`, `max_fields_per_batch`

**Behavior:** Copy selected source fields while choosing first, last, or all occurrences and an explicit destination collision policy.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `MARC field before operation`

**After:** `MARC field after operation`

**Stored representation:** Structured `copy-fields-with-policy` parameters validated by the task form.

**Related:** none

## Copy subfield within field

**Operation kind:** `copy-subfield`

**Purpose:** Within each matching field, copy each existing source subfield's value into a new subfield with the destination code. Useful for invalidating in place ($a → $z).

**When to use:** Use copy subfield within field when that specific MARC change is required.

**Inputs:** `tag`, `src_code`, `dst_code`

**Behavior:** Within each matching field, copy each existing source subfield's value into a new subfield with the destination code. Useful for invalidating in place ($a → $z).

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `035 $a abc`

**After:** `035 $a abc $z abc`

**Stored representation:** Structured `copy-subfield` parameters validated by the task form.

**Related:** none

## Custom Python (advanced)

**Operation kind:** `custom`

**Purpose:** Drop in raw Python for anything the palette doesn't cover.

**When to use:** Use custom python (advanced) when that specific MARC change is required.

**Inputs:** `code`

**Behavior:** Drop in raw Python for anything the palette doesn't cover.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `(technical Python operation)`

**After:** `(technical Python operation remains unchanged)`

**Stored representation:** Structured `custom` parameters validated by the task form.

**Related:** none

## Delete 856 by URL regex

**Operation kind:** `delete-856-url-regex`

**Purpose:** Remove 856 fields whose URL matches the given regex (re.search; case-insensitive by default).

**When to use:** Use delete 856 by url regex when that specific MARC change is required.

**Inputs:** `pattern`, `ignore_case`

**Behavior:** Remove 856 fields whose URL matches the given regex (re.search; case-insensitive by default).

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `856 $u https://example.org/item.pdf`

**After:** `(856 removed when URL matches the regex)`

**Stored representation:** Structured `delete-856-url-regex` parameters validated by the task form.

**Related:** none

## Delete 856 by URL text

**Operation kind:** `delete-856-url-contains`

**Purpose:** Remove 856 fields whose URL contains the given text.

**When to use:** Use delete 856 by url text when that specific MARC change is required.

**Inputs:** `match`

**Behavior:** Remove 856 fields whose URL contains the given text.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `856 $u https://old.example/item`

**After:** `(856 removed when URL contains the configured text)`

**Stored representation:** Structured `delete-856-url-contains` parameters validated by the task form.

**Related:** none

## Delete fields matching a field filter

**Operation kind:** `delete-by-subfield`

**Purpose:** Remove only fields selected by indicators or subfield values.

**When to use:** Use delete fields matching a field filter when that specific MARC change is required.

**Inputs:** `tag`, `match`, `predicate`

**Behavior:** Remove only fields selected by indicators or subfield values.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `650 $a History $2 local`

**After:** `(650 removed when a subfield contains the match)`

**Stored representation:** Structured `delete-by-subfield` parameters validated by the task form.

**Related:** none

## Delete subfield when value matches

**Operation kind:** `delete-subfield-if-value`

**Purpose:** Strip a subfield only when its value matches exact text, contains text, or matches a regex.

**When to use:** Use delete subfield when value matches when that specific MARC change is required.

**Inputs:** `tag`, `code`, `value`, `match`, `trim`, `ignore_case`

**Behavior:** Strip a subfield only when its value matches exact text, contains text, or matches a regex.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `856 $u https://example.org $y obsolete`

**After:** `856 $u https://example.org`

**Stored representation:** Structured `delete-subfield-if-value` parameters validated by the task form.

**Related:** none

## Delete subfields by code

**Operation kind:** `delete-subfield`

**Purpose:** Strip the listed subfield codes from every field with the given tag. Multiple codes are comma- or space-separated.

**When to use:** Use delete subfields by code when that specific MARC change is required.

**Inputs:** `tag`, `codes`

**Behavior:** Strip the listed subfield codes from every field with the given tag. Multiple codes are comma- or space-separated.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `650 $a History $9 local`

**After:** `650 $a History`

**Stored representation:** Structured `delete-subfield` parameters validated by the task form.

**Related:** none

## Delete tag

**Operation kind:** `delete-tag`

**Purpose:** Remove every field with this tag.

**When to use:** Use delete tag when that specific MARC change is required.

**Inputs:** `tag`

**Behavior:** Remove every field with this tag.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `029 $a obsolete`

**After:** `(029 field removed)`

**Stored representation:** Structured `delete-tag` parameters validated by the task form.

**Related:** none

## Find & replace in subfield

**Operation kind:** `subfield-replace`

**Purpose:** Replace text inside a specific subfield code on a tag. Toggle **Treat Find as regex** for pattern-based finds; leave it off for literal text.

**When to use:** Use find & replace in subfield when that specific MARC change is required.

**Inputs:** `tag`, `code`, `find`, `replace`, `regex`, `ignore_case`

**Behavior:** Replace text inside a specific subfield code on a tag. Toggle **Treat Find as regex** for pattern-based finds; leave it off for literal text.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `035 $a TFeba9780203066140`

**After:** `035 $a (SCTFEBA)9780203066140`

**Stored representation:** Structured `subfield-replace` parameters validated by the task form.

**Related:** none

## Guided find and replace

**Operation kind:** `guided-find-replace`

**Purpose:** Find text in one MARC value and replace it while preserving surrounding text by default.

**When to use:** Use this for a guided literal or raw-regex edit in a control field, one subfield, or all subfield values.

**Inputs:** `target_kind`, `tag`, `subfield`, `match_mode`, `find`, `ignore_case`, `replacement_mode`, `replacement`, `occurrences`, `value_scope`, `condition`

**Behavior:** Matched-text mode changes only the matching text; whole-value mode replaces the selected value; prepend and append preserve the original value.

**Preserves:** Text before and after a match is preserved unless whole-value replacement is selected.

**Skip behavior:** Values without a match are unchanged; first/all and first/last selected-value scope are explicit.

**Error behavior:** Invalid target, pattern, capture, or incompatible mode blocks save or execution.

**Before:** `035 $a TFeba9780203066140`

**After:** `035 $a (SCTFEBA)9780203066140`

**Stored representation:** Structured target, match mode, replacement mode, occurrence, and case parameters; raw regex is opt-in.

**Related:** `subfield-replace`, `replace-field-data-by-regex`

## Imported empty-find subfield policy

**Operation kind:** `empty-find-subfield-policy`

**Purpose:** Apply an explicit add, replace, or ensure-one meaning to an imported empty Find instruction.

**When to use:** Use imported empty-find subfield policy when that specific MARC change is required.

**Inputs:** `tag`, `code`, `value`, `policy`

**Behavior:** Apply an explicit add, replace, or ensure-one meaning to an imported empty Find instruction.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `856 $u https://example.org`

**After:** `856 $u https://example.org $y Smith link`

**Stored representation:** Structured `empty-find-subfield-policy` parameters validated by the task form.

**Related:** none

## Move (re-tag) field

**Operation kind:** `move-field`

**Purpose:** Re-tag every field with the source tag as the destination tag. Same as Copy field followed by Delete tag, but in one atomic op.

**When to use:** Use move (re-tag) field when that specific MARC change is required.

**Inputs:** `src_tag`, `dst_tag`

**Behavior:** Re-tag every field with the source tag as the destination tag. Same as Copy field followed by Delete tag, but in one atomic op.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `490 $a Series`

**After:** `830 $a Series`

**Stored representation:** Structured `move-field` parameters validated by the task form.

**Related:** none

## RDA: classify content, media, and carrier

**Operation kind:** `rda-classify-material`

**Purpose:** Add explicit 336, 337, and 338 fields from checked-in Leader/007 evidence or a cataloger-selected material type.

**When to use:** Use when a record needs deterministic RDA content, media, and carrier fields.

**Inputs:** `mode`, `fixed_material`, `existing_field_action`

**Behavior:** Combines content evidence from Leader/06 with explicit 007 media/carrier evidence; print text and maps use physical carriers, while 007 cr identifies online resources.

**Preserves:** Existing 336/337/338 fields are preserved by default.

**Skip behavior:** Records with no unambiguous Leader/007 mapping fail with the evidence instead of guessing.

**Error behavior:** Unsupported material values and ambiguous evidence block the operation before adoption.

**Before:** `Leader/06=m; 007 cr`

**After:** `336 $a computer program $b cop
337 $a computer $b c
338 $a online resource $b cr`

**Stored representation:** Mode, fixed material override, and existing-field policy.

**Related:** `rda-mark-rda`, `rda-promote-260`

## RDA: expand reviewed abbreviations

**Operation kind:** `rda-expand-abbreviations`

**Purpose:** Expand the reviewed abbreviation map in 300 $a.

**When to use:** Use only for the checked-in reviewed abbreviations.

**Inputs:** none

**Behavior:** Replaces exact reviewed tokens such as p., ill., and col.

**Preserves:** Other 300 text and all unrelated fields remain unchanged.

**Skip behavior:** Unrecognized abbreviations are preserved.

**Error behavior:** Malformed records fail without free-text rewriting.

**Before:** `300 $a 1 p. : ill.`

**After:** `300 $a 1 pages : illustrations`

**Stored representation:** The operation kind selects the checked-in mapping table.

**Related:** `rda-mark-rda`

## RDA: mark 040 $e rda

**Operation kind:** `rda-mark-rda`

**Purpose:** Ensure the first 040 contains the explicit RDA description term.

**When to use:** Use when local policy requires 040 $e rda.

**Inputs:** none

**Behavior:** Adds $e rda once, creating 040 only when it is absent.

**Preserves:** All existing 040 subfields remain unchanged.

**Skip behavior:** An existing 040 $e rda is unchanged.

**Error behavior:** Malformed MARC records fail through the normal task error path.

**Before:** `040 $a DLC $b eng`

**After:** `040 $a DLC $b eng $e rda`

**Stored representation:** No opaque external setting; the operation kind is the policy.

**Related:** `rda-classify-material`

## RDA: normalize known relator codes

**Operation kind:** `rda-normalize-relators`

**Purpose:** Add explicit $e terms for reviewed $4 relator codes while retaining the codes.

**When to use:** Use when local policy prefers spelled-out relator terms.

**Inputs:** none

**Behavior:** Maps only the reviewed aut, edt, trl, and pbl codes, adding a missing term once.

**Preserves:** The original $4 code, existing relator terms, unknown values, and unrelated subfields remain unchanged.

**Skip behavior:** Fields without a reviewed code are unchanged.

**Error behavior:** Malformed records fail rather than applying a guessed mapping.

**Before:** `100 1  $a Doe $4 aut`

**After:** `100 1  $a Doe $4 aut $e author`

**Stored representation:** The operation kind selects the checked-in mapping table.

**Related:** `rda-mark-rda`

## RDA: promote 260 to 264 when safe

**Operation kind:** `rda-promote-260`

**Purpose:** Retag 260 fields as 264 only when no 264 is already present.

**When to use:** Use when the publication statement is safe to promote without merging meanings.

**Inputs:** none

**Behavior:** Moves every 260 field to 264 with second indicator 1 (publication) when the record has no 264.

**Preserves:** Subfields and their relative order are preserved.

**Skip behavior:** Records with an existing 264 or no 260 are unchanged.

**Error behavior:** Ambiguous publication data is left unchanged rather than merged.

**Before:** `260    $a Boston : $b Press, $c 2024`

**After:** `264  1 $a Boston : $b Press, $c 2024`

**Stored representation:** The operation kind encodes the safe promotion rule.

**Related:** `rda-classify-material`

## RDA: remove GMD from 245 $h

**Operation kind:** `rda-remove-gmd`

**Purpose:** Remove an explicitly selected 245 $h GMD value.

**When to use:** Use when a legacy GMD must be removed during RDA cleanup.

**Inputs:** `value`

**Behavior:** Removes all 245 $h values when blank, or only the exact configured value.

**Preserves:** 245 title, statement, and unrelated subfields remain unchanged.

**Skip behavior:** Records without a matching 245 $h are unchanged.

**Error behavior:** Malformed input is reported; no blanket deletion of other fields occurs.

**Before:** `245 10 $a Title $h [electronic resource]`

**After:** `245 10 $a Title`

**Stored representation:** Explicit exact value parameter; blank means all 245 $h values.

**Related:** `rda-mark-rda`

## Replace field data by regex

**Operation kind:** `replace-field-data-by-regex`

**Purpose:** Apply a regex find/replace across every field with the given tag. Control fields edit `.data`; variable fields edit each subfield value.

**When to use:** Use replace field data by regex when that specific MARC change is required.

**Inputs:** `tag`, `pattern`, `replacement`, `ignore_case`

**Behavior:** Apply a regex find/replace across every field with the given tag. Control fields edit `.data`; variable fields edit each subfield value.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `008 230101s2023    xx            000 0 eng d`

**After:** `008 230101s2023    xx            000 0 eng d (matched data changed)`

**Stored representation:** Structured `replace-field-data-by-regex` parameters validated by the task form.

**Related:** none

## Replace matched subfield and indicators

**Operation kind:** `replace-field-subfield-and-indicators`

**Purpose:** For fields matching tag, indicators, subfield code, and subfield value (exact or regex), update the indicators and that subfield value.

**When to use:** Use replace matched subfield and indicators when that specific MARC change is required.

**Inputs:** `tag`, `match_code`, `match_value`, `regex`, `ignore_case`, `new_ind1`, `new_ind2`, `match_ind1`, `match_ind2`, `new_code`, `new_value`

**Behavior:** For fields matching tag, indicators, subfield code, and subfield value (exact or regex), update the indicators and that subfield value.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `035 00 $a TFeba9780203066140`

**After:** `035 09 $a (SCTFEBA)`

**Stored representation:** Structured `replace-field-subfield-and-indicators` parameters validated by the task form.

**Related:** none

## Set 008 form-of-item to 'o' (online)

**Operation kind:** `set-008-form`

**Purpose:** Mark form of item as online at one explicit 008 byte or at the byte selected from the Leader.

**When to use:** Use the Leader option for normal cataloger authoring; imported proven external patterns retain their original fixed position 23 or 29.

**Inputs:** `position`

**Behavior:** Writes o at byte 23 or 29. An explicit position is independent of Leader type, preserving the proven external instruction exactly.

**Preserves:** Every other 008 byte and all other fields remain unchanged.

**Skip behavior:** Leader-based mode leaves unsupported record types unchanged; missing or short 008 fields are unchanged.

**Error behavior:** Any position other than Leader, 23, or 29 fails before generated task execution.

**Before:** `008 230101s2023    xx            000 0 eng d`

**After:** `008 230101s2023    xx o          000 0 eng d`

**Stored representation:** Structured position choice: Leader, 23, or 29.

**Related:** `sort-fields`

## Set control field

**Operation kind:** `set-control-field`

**Purpose:** Set a complete control value or one fixed character position.

**When to use:** Use set control field when that specific MARC change is required.

**Inputs:** `tag`, `mode`, `value`, `position`, `condition`

**Behavior:** Set a complete control value or one fixed character position.

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `MARC field before operation`

**After:** `MARC field after operation`

**Stored representation:** Structured `set-control-field` parameters validated by the task form.

**Related:** none

## Set indicators

**Operation kind:** `edit-indicators`

**Purpose:** Override one or both indicators on every field with the given tag. Leave an indicator blank to keep the existing value (use a space to set blank).

**When to use:** Use set indicators when that specific MARC change is required.

**Inputs:** `tag`, `ind1`, `ind2`

**Behavior:** Override one or both indicators on every field with the given tag. Leave an indicator blank to keep the existing value (use a space to set blank).

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `245 10 $a Title`

**After:** `245 00 $a Title`

**Stored representation:** Structured `edit-indicators` parameters validated by the task form.

**Related:** none

## Sort fields by tag

**Operation kind:** `sort-fields`

**Purpose:** Reorder all variable fields by tag (used as a final step).

**When to use:** Use sort fields by tag when that specific MARC change is required.

**Inputs:** none

**Behavior:** Reorder all variable fields by tag (used as a final step).

**Preserves:** Unrelated fields and values remain unchanged.

**Skip behavior:** Records that do not match the operation are unchanged.

**Error behavior:** Invalid inputs are reported before the task is saved or run.

**Before:** `040 $a ABC
020 $a 123`

**After:** `020 $a 123
040 $a ABC`

**Stored representation:** Structured `sort-fields` parameters validated by the task form.

**Related:** none

## Structural find and replace

**Operation kind:** `structural-find-replace`

**Purpose:** Conditionally replace complete fields, retag fields, set indicators, or operate over a validated tag range.

**When to use:** Use structural find and replace when a whole-field or structural tag/indicator change is required.

**Inputs:** `target_kind`, `tag`, `start_tag`, `end_tag`, `subfield`, `match_mode`, `find`, `pattern_pieces`, `action`, `replacement`, `replacement_pieces`, `replacement_ind1`, `replacement_ind2`, `replacement_subfields`, `match_ind1`, `match_ind2`, `match_subfields`, `destination_tag`, `new_ind1`, `new_ind2`, `occurrences`, `ignore_case`, `predicate`

**Behavior:** Matched fields are changed in their existing source position. Retagging changes the tag but does not sort the record; add the explicit Sort Fields operation afterward when canonical tag order is required.

**Preserves:** Unrelated fields and values remain unchanged; retagging preserves the field's source position until an explicit sort.

**Skip behavior:** Records and fields that do not match are unchanged.

**Error behavior:** Invalid targets, ranges, patterns, replacement pieces, or incompatible actions block saving or execution.

**Before:** `956 40 $u https://example.org`

**After:** `856 40 $u https://example.org (same source position until sorted)`

**Stored representation:** Structured target, match, action, occurrence, and replacement parameters validated by the task form.

**Related:** `sort-fields`

## Common field changes

Tasks → Quick changes uses one **Quick operation** dropdown. It combines Find and replace, the nine Common field changes below, and the existing specialized Quick cleanups. Each choice is a one-operation edit: read its summary, Preview, then Apply the same current preview. Only the selected operation's controls are shown. Existing fields are filtered before the First, Last, Numbered, or Every occurrence is chosen. Records missing a requested occurrence are skipped and grouped by reason. Guided matching is the normal path; an optional Advanced regular expression is available when needed. Preview and Apply are recoverable, and a changed operation requires a new Preview; harmless form values remain available when you return to an operation.

These nine labels are alphabetical. Choose exactly one for each Preview and Apply cycle.

### Add field

**Purpose:** Add one explicitly described control or data field.

**When to use:** Use when a field should be added once without saving a task.

**Inputs:** destination tag, indicators, subfields or control value, record scope

**Behavior:** Adds the field to every record, or only when its tag or complete identity is absent.

**Preserves:** Existing fields, their values, and their source order remain unchanged.

**Skip behavior:** A record is unchanged when its selected add-field scope says the field is already present.

**Error behavior:** Invalid tags, indicators, control values, or subfield rows block Preview.

**Before:** `(no 877 field)`

**After:** `877  $m Map`

**Related:** none

### Add subfield

**Purpose:** Append or prepend one code and value to selected variable fields.

**When to use:** Use when existing fields need one explicit subfield added.

**Inputs:** field filter, occurrence, subfield code, subfield value, position, repeat policy

**Behavior:** Adds the pair to the fields that pass the filter and then the chosen occurrence.

**Preserves:** Field tags, indicators, existing ordered subfields, and unrelated fields remain unchanged.

**Skip behavior:** Records with no matching occurrence are skipped and listed by the selector reason.

**Error behavior:** Control fields, invalid codes, and invalid matcher values block Preview.

**Before:** `856 40 $u https://vendor.example/item`

**After:** `856 40 $u https://vendor.example/item $y Vendor link`

**Related:** `delete-subfield`

### Copy field

**Purpose:** Deep-copy selected complete fields to one destination tag.

**When to use:** Use when selected fields should also appear under another tag.

**Inputs:** field filter, occurrence, destination tag, destination policy

**Behavior:** Copies only fields resolved after filtering and occurrence selection; choose Append, Skip identical, or Replace all destination fields.

**Preserves:** Source fields and complete indicators and subfield order are preserved.

**Skip behavior:** Records without a selected source field are skipped without changing destination fields.

**Error behavior:** Incompatible control/data tags or invalid destination policies block Preview.

**Before:** `245 10 $a Title`

**After:** `245 10 $a Title
246 30 $a Title`

**Related:** none

### Delete field

**Purpose:** Remove selected complete fields.

**When to use:** Use when only a chosen occurrence or filtered set should be removed.

**Inputs:** field filter, occurrence

**Behavior:** Removes the fields that pass the filter and then the selected First, Last, Numbered, or Every occurrence.

**Preserves:** All non-selected fields and the relative order of remaining fields remain unchanged.

**Skip behavior:** Records with no selected occurrence are skipped and grouped by reason.

**Error behavior:** Invalid tags, filters, occurrence choices, or unsafe matchers block Preview.

**Before:** `856 40 $u https://old.example/item`

**After:** `(selected 856 field removed)`

**Related:** none

### Delete subfield

**Purpose:** Remove one code from selected variable fields, optionally matching its value.

**When to use:** Use when a subfield must be removed from only the intended fields.

**Inputs:** field filter, occurrence, subfield code, value match, subfield occurrence, remove empty field

**Behavior:** Removes the first or every matching subfield after field filtering and occurrence selection.

**Preserves:** Other subfields, field identity, and unrelated fields remain unchanged unless empty-field removal is selected.

**Skip behavior:** Missing fields or values are skipped and reported by reason rather than guessed.

**Error behavior:** Control fields, invalid codes, and invalid guided or regular-expression matchers block Preview.

**Before:** `856 40 $u https://vendor.example/item $y obsolete`

**After:** `856 40 $u https://vendor.example/item`

**Related:** `add-subfield`

### Move or retag field

**Purpose:** Change selected fields to a destination tag while retaining their complete contents.

**When to use:** Use when a field needs a new tag but should stay in its current record position.

**Inputs:** field filter, occurrence, destination tag

**Behavior:** Retags only the selected fields; it does not sort or otherwise reorder the record.

**Preserves:** Indicators, ordered subfields, values, and source positions are preserved. Reorder fields is a separate explicit Quick action.

**Skip behavior:** Records without a selected occurrence are skipped and grouped by selector reason.

**Error behavior:** Incompatible control/data tags and invalid destination tags block Preview.

**Before:** `490  $a Series`

**After:** `830  $a Series (same source position)`

**Related:** `sort-fields`

### Remove exact duplicate fields

**Purpose:** Remove repeated fields only when their complete MARC identity is exactly equal.

**When to use:** Use when exact duplicates should be reduced while near-duplicates remain for review.

**Inputs:** field filter, keep first or last

**Behavior:** Groups filtered fields by tag, indicators or control value, and ordered subfield code/value pairs, then keeps the chosen copy.

**Preserves:** Near-duplicates, unique fields, and the relative order of surviving fields remain unchanged.

**Skip behavior:** Records with no duplicate group are unchanged; no similar field is treated as a duplicate.

**Error behavior:** Invalid duplicate filters or keep choices block Preview.

**Before:** `035  $a (OCoLC)123
035  $a (OCoLC)123`

**After:** `035  $a (OCoLC)123`

**Related:** none

### Set indicators

**Purpose:** Set indicator 1, indicator 2, or both on selected data fields.

**When to use:** Use when selected fields need explicit indicator values without changing their data.

**Inputs:** field filter, occurrence, indicator 1, indicator 2

**Behavior:** Writes only the chosen indicator values on fields resolved after filtering and occurrence selection.

**Preserves:** Tags, ordered subfields, values, and unchanged indicators remain intact.

**Skip behavior:** Records with no selected occurrence or no effective change are unchanged and reported accordingly.

**Error behavior:** Control fields, missing indicator choices, or invalid filters block Preview.

**Before:** `245 10 $a Title`

**After:** `245 00 $a Title`

**Related:** none

### Swap field occurrences

**Purpose:** Exchange two distinct complete fields with the same tag.

**When to use:** Use when two same-tag fields need their source-order positions exchanged.

**Inputs:** first field filter and occurrence, second field filter and occurrence

**Behavior:** Swaps the complete selected field objects, preserving each field's tag, indicators, control value, and ordered subfields.

**Preserves:** Field contents are untouched; only the two selected source positions change.

**Skip behavior:** Missing sides and selectors resolving to the same field are skipped and grouped by reason.

**Error behavior:** Selectors must be distinct and use the same exact tag; Every is not available for Swap.

**Before:** `070  4 $a QA76.73.P98
070  4 $a QA76.73.P99`

**After:** `070  4 $a QA76.73.P99
070  4 $a QA76.73.P98`

**Related:** none

### Worked examples

To swap two distinguishable 070 fields, choose **Swap field occurrences**, enter tag `070`, and select the first and second occurrences. The complete fields exchange positions; each indicator, value, and ordered subfield stays with its field.

To select one of several 856 fields, enter tag `856`, choose subfield `$u`, use the guided **Contains** match for the vendor text, then choose **Numbered** for the requested matching occurrence. Filtering happens before numbering, so a nonmatching vendor link is not counted.

**Move or retag field** keeps the source position. Use the separate explicit **Reorder fields** Quick action when tag order should be normalized.

Exact duplicate removal compares complete field identity (tag, indicators or control value, and ordered subfields); near-duplicates are retained.

Preview and Apply are recoverable: reset clears preview evidence, stale source or changed selectors disable Apply, and a successful Apply creates the existing history or recoverable file-version evidence.
