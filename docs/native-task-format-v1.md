# Native Task Format Version 1

Smith Metadata Studio's native task format is a portable, non-executable JSON
document. The checked-in Draft 2020-12 schema is
`marcedit_web/schemas/native-task-v1.schema.json`. A document has exactly four
top-level fields: `schema_version`, `name`, `description`, and the ordered
`steps` array. Step IDs must be unique, and array order is execution order.

Version 1 is the only supported schema version. It supports these actions:

- `delete_tag`, with an explicit three-character MARC tag;
- `build_field`, with an explicit target tag, two indicators, structured
  subfields, missing-source policy, and existing-target policy; and
- `sort_fields`.

Unknown schema versions and actions fail validation. The program does not
guess how a future version or unsupported action should behave, and native
definitions cannot contain Python, custom actions, or unresolved review
state.

## Structured Build Field example

Build Field values are represented as ordered segment objects rather than
template strings. A segment is either literal `text` or a reference to a
three-digit `control_field`. `missing_source` is explicitly
`skip_and_report`; `existing_target` is explicitly either `append` or `skip`.

This synthetic 876 example is the checked-in
`tests/fixtures/native_tasks/build-field.json` fixture:

```json
{
  "schema_version": 1,
  "name": "build-holdings-field",
  "description": "Build an 876 from control fields 003 and 001.",
  "steps": [
    {
      "id": "build-876",
      "action": "build_field",
      "target": {
        "tag": "876",
        "indicators": [" ", " "]
      },
      "subfields": [
        {
          "code": "a",
          "segments": [
            {"type": "text", "value": "B("},
            {"type": "control_field", "tag": "003"},
            {"type": "text", "value": ")"},
            {"type": "control_field", "tag": "001"},
            {"type": "text", "value": "-SC"}
          ]
        },
        {
          "code": "l",
          "segments": [
            {"type": "text", "value": "Internet"}
          ]
        }
      ],
      "missing_source": "skip_and_report",
      "existing_target": "append",
      "source": {
        "format": "marcedit-task",
        "line": 7,
        "instruction_sha256": "8c7d6e7a5a3d94fcd03d0c51ef9b2210d21f7296a28e571f8f5ab1a8ab58ef91"
      }
    }
  ]
}
```

The optional `source` object is privacy-safe provenance, not executable input.
It records only the external format, source line number, and normalized
instruction SHA-256. Portable documents must not include institutional
records, original task lines, staff identity, local URLs, or other local task
corpus content.

## Canonicalization and execution snapshots

Import validates JSON against version 1 and returns the validated object.
Export writes UTF-8 JSON with object keys sorted, compact separators, array
order preserved, and one trailing newline. The canonical JSON stored in the
database uses the same representation without the trailing newline. An
export/import round trip therefore preserves step order and values.

The native JSON remains the source of truth. The application compiles it
deterministically through the existing operation-to-Python bridge and stores
the generated body, imports, and current compiler fingerprint atomically with
the canonical definition. The fingerprint is the SHA-256 of the canonical
checked-in manifest at
`marcedit_web/schemas/native-task-compiler-contract-v1.json`; runtime
fingerprinting reads that packaged manifest and does not compile or read test
fixtures. Tests recompile the synthetic golden definitions to keep the
manifest fresh.

A stale fingerprint causes revision-checked regeneration of both execution
snapshots and an audit event. If validation or compilation fails, or the task
changes during migration, the stored row is left unchanged and execution is
blocked. If a current fingerprint's stored body or imports differ from fresh
compilation, the mismatch is an integrity failure: it is not repaired or run
as legacy code.

Existing form-built and raw-Python tasks remain legacy tasks with null native
definition and fingerprint fields. They are not rewritten by the schema
migration and continue through the established authorization and execution
path. A legacy save cannot overwrite a native task.

Version 1 defines the portable contract and storage boundary only.
Cataloger-facing structured authoring, external task import and migration,
compatibility-corpus work, and preview promotion will arrive in later TASK-174
child tickets.
