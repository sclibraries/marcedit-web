Title: Add the native task schema and storage compatibility layer

Parent: TASK-174

Scope:
- Publish and validate version 1 of the non-executable native task JSON schema.
- Add deterministic canonical serialization and fail closed on unknown schema
  versions before editing, compilation, preview, or execution.
- Add nullable native-definition and compiler-fingerprint storage without
  rewriting existing form-built or raw-Python task rows.
- Compile validated native definitions through the existing deterministic
  operation-to-Python bridge and store the canonical definition, generated
  body/import snapshots, and compiler fingerprint atomically.
- Add a checked-in compiler contract manifest whose canonical SHA-256 digest
  changes when golden generated snapshots or supported contract versions
  change.
- Regenerate snapshots atomically when a stored fingerprint is stale, audit
  the migration, and leave the prior row unchanged if migration fails.
- Treat same-fingerprint snapshot mismatches as integrity failures with no
  fallback to stale generated code.
- Preserve existing task authorization and all legacy task behavior.

Success Criteria:
- Schema-version 1 definitions validate and export/import without changing
  step order or values.
- Unknown schema versions report both encountered and supported versions and
  cannot be saved or run.
- Existing tasks remain readable and runnable with null native fields.
- Native saves and compiler migrations are atomic under task revision checks.
- Compiler-fingerprint changes migrate valid native rows and emit an audit
  event containing old and new fingerprints.
- Compilation, validation, revision-race, or integrity failures leave stored
  rows unchanged and block execution.
- Golden definitions and generated snapshot hashes are enforced by a freshness
  test.
- Focused and complete supported Docker suites pass with every skip reported.
- Independent review has no unresolved Critical or Important findings.

Status: In-Progress

Design:
- `docs/superpowers/specs/2026-07-29-smith-metadata-studio-open-task-migration-design.md`

Plan:
- `docs/superpowers/plans/2026-07-30-task-178-native-task-schema-storage.md`
