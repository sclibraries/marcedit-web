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

Pre-review Evidence:
- Implementation commits:
  - `3510622a1dd0379de7c1f6ea73395f8f79b45bfb` — native schema and
    compiler;
  - `cc17490c33459ba3352ad4da612bf6d22f9c00b0` — literal structured
    Build Field segment preservation;
  - `b9d5a1fe64d376827cac73458a2c5df89d11c953` — compiler contract
    manifest and fingerprint;
  - `b8352a381bc1b494db13808233e235f8d8c809cf` — atomic schema-v14
    native storage;
  - `eba053297e70e61712fbb5b3c7a5412cdd9e26c1` — legacy/native update
    race protection;
  - `39153d4a7abf156d0627f7440be971276c3927ef` — execution snapshot
    verification, migration, materialization, and audit; and
  - `1b1b77d9a3791bec892817af2553309e998581b7` — deferred review
    follow-ups for runtime fingerprint isolation and the typed compiler plan
    example. The isolation regression passed 8 contract tests and failed under
    a deliberate mutation that introduced runtime golden-fixture verification.
- Schema version `1` validates and compiles exactly `delete_tag`,
  `build_field`, and `sort_fields`. Structured Build Field text and
  control-field segments remain typed through the compiler bridge.
- The schema-v13-to-v14 preservation regression passed: migration is
  idempotent, the legacy body and imports remain unchanged, native definition
  and fingerprint remain null, and the existing row receives revision `1`.
- The checked-in golden manifest matched every synthetic definition in the
  candidate image. Its canonical SHA-256 fingerprint is
  `dd28c3725eeeb2c1300435d846e33214938f01473759341d913e34a7b83d6dd4`;
  runtime fingerprinting reads the packaged manifest without compilation or
  test-fixture access.
- Focused storage regressions passed for pre-connection validation and
  compilation, atomic canonical definition/body/import/fingerprint saves,
  expected-revision updates, stale revision refusal without mutation,
  byte-identical compile-failure rollback, legacy-to-native revision checks,
  and native protection from losing legacy-update races.
- Execution regressions passed for byte-for-byte current-fingerprint body and
  import integrity checks, stale-fingerprint snapshot regeneration, invalid
  stored definition refusal, compiler-failure rollback, revision-race CAS
  refusal, legacy compiler bypass, parseable materialization, and no output
  file on integrity failure. Successful stale migration increments revision
  and emits `native-task-compiler-migrated` only after commit with owner, task,
  old fingerprint, new fingerprint, and audit user.
- `docker build -t marcedit-web:task-178 .` exited `0`. The network-disabled
  artifact check exited `0` with no output and proved that `jsonschema`,
  `LICENSE`, `THIRD_PARTY_NOTICES.md`, the version-1 schema, and the compiler
  contract manifest are packaged.
- The exact focused candidate suite passed `101` tests with `0` skips in
  `3.27s`. The complete candidate suite passed `1,634` tests with `4` skips in
  `49.54s`. All skips are disclosed: two parametrizations at
  `tests/test_docker_compose_config.py:88` and two at
  `tests/test_docker_compose_config.py:130`, each because the Docker CLI is
  required to render Compose configuration and is absent from the
  network-disabled candidate image.
- `git diff --check 4ccc4e1..HEAD` passed. The required path and identifier
  audit found no changes under `deploy/`, `scripts/`, `.streamlit/`, Compose,
  systemd, proxy, worker, cataloger UI, or authorization modules; established
  `MARCEDIT_WEB_*`, `/marcedit-web/`, and `MarcEditor` identifiers remain.
  No `MarcEdit Tasks/` path is tracked, and the two native task fixtures are
  synthetic.
- Status remains `In-Progress` pending Task 5 independent task and whole-branch
  review. No Step 7 completion action has been taken.
