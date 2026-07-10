# FOLIO Rule Profiles Design

Ticket: [TASK-148](../../../.tickets/TASK-148-folio-rule-profiles.md)

## Summary

Add FOLIO validation profiles with safe assisted fixes. Catalogers choose a
workflow profile, review FOLIO-specific issues in Validate, and can apply
deterministic fixes either one record at a time or in batch after preview.

The first version does not call FOLIO APIs. It prepares and validates local
MARC records for FOLIO Data Import and round-tripping standards.

## Goals

- Support FOLIO workflow context instead of one hard-coded load-readiness pass.
- Reduce manual cataloger work through safe, deterministic fixes.
- Keep every change visible, previewable, and recorded in existing history.
- Preserve large-file behavior by streaming validation and avoiding full-batch
  materialization in Streamlit state.
- Let local standards be adjusted without changing Python code.

## Non-Goals

- Direct FOLIO API integration.
- Silent normalization during export.
- Automatically resolving ambiguous cataloging choices.
- Replacing generic MARC validation from `data/marc-rules.txt`.
- Building a general rule language as powerful as Python tasks.

## Existing Context

The current Validate page combines three issue sources:

- `preflight.run_preflight`
- `rules_validate.validate_records`
- `load_readiness.validate_records`

`load_readiness.py` already emits hard-coded FOLIO / EDS warnings for fixed
fields and RDA carrier fields. This feature should generalize that path into
profile-driven FOLIO checks rather than add a separate validation system.

The Tasks page is useful precedent for adjustable, shareable user-owned
definitions, but FOLIO profiles should not execute arbitrary Python. Rules
should be structured data with a constrained evaluator and constrained fix
operations.

## Profiles

Seed these profiles in v1:

- `folio-new-instance`: loading new Instance / MARC SRS records.
- `folio-round-trip`: round-tripping existing Instance / MARC SRS records.
- `folio-ecollection-ebook`: e-collection ebook standards, layered on top of
  either new-load or round-trip context.

The UI should let a cataloger select one primary FOLIO workflow profile. If
the ebook profile is implemented as an add-on, the UI can expose it as a
checkbox such as "Apply e-collection ebook rules".

## Rule Model

Rules are structured records, stored in SQLite and seeded with defaults. A
rule has:

- stable key
- display label
- profile membership
- severity: `error`, `warning`, or `info`
- target: field, subfield, indicator, fixed-field byte, or field group
- requirement: required, forbidden, recommended, equals, not-in, pattern, or
  either-group-present
- fix operation: none, remove field, add static field, set byte, add subfield,
  or normalize configured field template
- configured values, when needed
- enabled flag

Only admins should edit shared seeded rules. Catalogers can use shared profiles
while ordinary task permissions remain unchanged.

## Seeded FOLIO Rules

Initial default rules should cover the standards from the ticket:

- For new Instance / SRS load, `001` must not be present.
- For round-trip, `001` must be present.
- `035 9\` with the local Five Colleges container code should be present when
  the profile has a configured value.
- `008` byte 29 must not be `s`, `z`, or `o`; scores can use `|` when the
  profile says score loading is active.
- `506 1\` should be included for multi-institution loads and is otherwise
  preferred.
- `655 \7 $a Electronic books. $2 local` is required for ebook profiles.
- `710 2\ $a <configured value> $2 local` is recommended when configured.
- `830 \0 $a <configured value> $2 local` is recommended when configured.
- Loading path must include either `852`, `856`, `876`, and `877`, or a valid
  `949 \\` field with required subfields.
- `949 $u`, `$y`, `$t`, `$p`, `$h` or `$h` plus `$i`, `$l`, `$b`, and `$m`
  should be present when using the `949` path.
- `949 $b` barcode must end in dash plus a configured two-letter institution
  code, such as `-SC`.

## Safe Fix Policy

A fix is safe only when the app can produce the exact intended MARC bytes from
the selected profile and current record.

Safe in v1:

- Remove `001` in the new-load profile.
- Add configured static fields such as `035`, `655`, `710`, or `830`.
- Set a configured fixed-field byte when the field exists and has valid length.
- Add missing configured `949` subfields when values are present in the
  profile or supplied in the preview form.
- Normalize a configured barcode suffix by appending or replacing the suffix
  only when the existing barcode stem is non-empty.

Check-only in v1:

- Missing `001` in round-trip records. The app cannot infer the correct
  Instance / SRS link.
- Choosing whether `506` applies when the profile is not explicitly marked
  multi-institution.
- Choosing local `710` or `830` values when no configured value exists.
- Choosing whether to use the holdings/item field path or the `949` path when
  neither group is present.
- Any deletion other than removing forbidden `001` in the new-load profile.

## UI Flow

Validate gains a FOLIO section above the issue table:

- FOLIO profile selector.
- Optional profile inputs, such as container code, institution suffix, link
  language, collection name, and score-loading mode.
- "Run FOLIO checks" uses the selected profile in the existing validation
  pipeline.

Issue rows should include whether a safe fix is available. The existing
record modal should expose a per-record fix action for a selected issue when
there is exactly one deterministic correction.

Batch flow:

1. Cataloger clicks "Preview safe fixes".
2. App streams through records and builds a compact fix preview summary.
3. Preview lists counts by rule, affected record numbers, and representative
   before/after snippets.
4. Cataloger confirms.
5. App applies fixes through the disk-backed record store and creates the same
   kind of history/provenance snapshot used by other mutating operations.
6. Validate cache is cleared and issues recompute against the updated file.

Per-record flow:

1. Cataloger filters or selects an issue in Validate.
2. Cataloger opens the record.
3. If the issue has a safe fix, the modal offers "Apply fix".
4. App applies only that fix to that record, creates history/provenance, clears
   validation cache, and returns to Validate.

## Data Flow

Add a new library module, likely `marcedit_web/lib/folio_profiles.py`, with:

- profile loading and seeding
- rule evaluation
- safe-fix planning
- safe-fix application helpers

The Validate renderer should call the FOLIO evaluator after generic validation.
FOLIO issues should use the existing `Issue` dataclass with codes prefixed by
`folio-`, for example `folio-new-load-forbidden-001`.

Safe-fix preview should return structured data, not rendered text, so tests can
verify the exact behavior and the UI can render it consistently.

## Storage

Add SQLite tables for profile and rule definitions, with a schema migration:

- `folio_profiles`
- `folio_rules`

The seeded defaults should be inserted idempotently. Future edits should not
be overwritten by seed re-runs unless a rule is missing.

Profile-specific runtime values can initially live in Streamlit session state
for preview and validation. Persisting per-job FOLIO settings is useful later
but not required for v1 unless the implementation needs it to keep previews
stable across reruns.

## Error Handling

- If a configured rule is malformed, show a file/profile-scope error and skip
  that rule.
- If a safe fix cannot be planned for a record, downgrade that record to a
  check-only issue with a clear suggestion.
- If applying fixes fails partway through, do not replace the active batch.
  Use the same temp-output-then-swap pattern as other disk-backed batch
  operations.
- Never silently apply FOLIO fixes during export.

## Performance

- Validation must operate over `store.iter_records()`.
- Preview should keep counts and small snippets, not copies of every record.
- Applying batch fixes should stream input to output.
- Streamlit session state should hold profile selections and preview summaries,
  not full record lists.

## Tests

Use TDD for implementation. Expected test areas:

- Profile seed migration creates default profiles and rules idempotently.
- New-load profile flags `001` and plans a safe remove fix.
- Round-trip profile flags missing `001` with no safe fix.
- Ebook profile flags missing `655` and can add configured static field.
- `008` byte 29 rules reject `s`, `z`, and `o`; score profile allows or sets
  `|` when configured.
- Loading-path rule accepts either holdings/item group or valid `949`.
- Barcode suffix rule validates the configured suffix.
- Batch preview reports counts without mutating the loaded records.
- Confirmed batch application mutates records and clears validation cache.
- Per-record fix applies only the selected record's selected fix.

## Open Cleanup

After this lands, `load_readiness.py` should either become a compatibility
wrapper around the FOLIO profile evaluator or be removed once callers migrate.
Do not keep two independent FOLIO validation implementations long-term.
