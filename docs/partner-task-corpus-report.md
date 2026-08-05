# Partner task corpus conversion report

This report is generated from the segregated partner corpus recorded by
TASK-191. It is a review artifact, not an execution fixture: the source task
files remain in `third_party/task-corpora/jenmawe-marcedit/` and are never
silently converted into runnable code.

- Source commit: `d07377a58cba9d0936a63863c9d428498609d5e5`
- Documents: 49
- Instructions: 1,239
- Converted by proven adapters: 693
- Actionable blockers: 546
- Unclassified instructions: 0
- Blockers without a cataloger next action: 0

The report is reproducible with:

```text
PYTHONPATH=. python3 scripts/audit_external_task_corpus.py \
  third_party/task-corpora/jenmawe-marcedit
```

## Blocker categories

| Count | External condition | Suggested next operation |
| ---: | --- | --- |
| 179 | `SUBFIELD_EDIT` option `102` | Imported Empty-Find Subfield Policy |
| 78 | Unproven `REPLACE` signature | Structural Find and Replace |
| 54 | `TASK_LIST` dependency | Import or select the referenced task, then confirm operations |
| 42 | Unfiltered `COPY` | Controlled Copy Fields: confirm occurrences and destination policy |
| 39 | Unsupported Leader condition | Add Field with a reviewed condition |
| 32 | `SUBFIELD_REMOVE` option `9` | Delete Subfield When Value Matches |
| 21 | Unproven field-filter match | Delete Fields Matching a Field Filter |
| 20 | Invalid/unsupported subfield-removal shape | Delete Subfield When Value Matches |
| 19 | Unsupported Build Field shape | Build Field with explicit policies |
| 8 | `SUBFIELD_EDIT` option suffix `2` | Guided Find and Replace |
| 7 | Enabled DELETE policy flag | Delete operation with explicit policy |
| 7 | Unsupported EDITFIELD option `2` | Set Control Field |
| 6 | Invalid ADD shape | Add Field |
| 5 | COPY filter flags differ from proven signature | Copy Field |
| 4 | `SUBFIELD_REMOVE` option `0` | Delete Subfield When Value Matches |
| 4 | Unproven `EDITFIELD` 001 semantics | Set Control Field |
| 3 | Unproven Build Field flags | Build Field with explicit policies |
| 2 | Unsupported DELETE option `2` | Delete Tag |
| 2 | Empty-find option `101|0` needs a policy choice | Imported Empty-Find Subfield Policy |
| 2 | `SUBFIELD_EDIT` option suffix `1` | Guided Find and Replace |
| 2 | Unproven EDITFIELD values for 947/003/956 | Set Control Field |
| 2 | `INDICATOR` instruction | Choose operation and confirm parameters |
| 2 | Short `SORTBY` instruction | Sort Fields |
| 1 | Opaque RDA option bundle | RDA Material Classification plus explicit operations |
| 1 | Unproven EDITFIELD 245 semantics | Set Control Field |

The category counts sum to 546. A blocker is intentionally retained as an
editable review item; no external option number or task dependency is guessed.
