# TASK-190 Example-Task Import Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Ticket:** [TASK-190](../../../.tickets/TASK-190-smith-core-import-completeness.md)

**Design:** [Example-task import completeness design](../specs/2026-08-02-task-190-example-task-import-completeness-design.md)

**Goal:** Convert every proven instruction shape in the supplied example-task corpus into editable deterministic operations and give every remaining instruction a clear, prefilled cataloger action.

**Architecture:** Parse external lines into a typed, evidence-bearing value, then dispatch through a complete adapter registry whose outputs are ordered structured operations or a draft-only migration blocker. Reusable field templates and predicates express cataloging intent without executing external syntax; successful imports open directly while partial imports remain editable but non-runnable.

**Tech Stack:** Python 3.9, Streamlit 1.50, pymarc, pytest, SQLite-backed task storage, the existing task compiler/sandbox, and Docker Compose.

## Global Constraints

- Keep the local MarcEdit Tasks corpus untracked. Commit only sanitized fixtures and a value-neutral compatibility manifest.
- Never execute, evaluate, or forward an external instruction to the native raw-regex engine.
- Preserve source order. One instruction may expand only into adjacent operations.
- Automatic conversions and suggestions must be structurally and visually distinct.
- Partial drafts may be saved, but preview, execution, submission, and runnable export must fail closed while a blocker remains.
- Every blocker must explain likely intent, why confirmation is required, what is preserved, and the recommended next action.
- Fully converted tasks open directly in the normal task editor; raw lines and fingerprints remain collapsed under Technical details.
- AI drafting behavior remains unchanged.
- Do not change the database schema, production directory, systemd, proxy, OAuth, worker topology, or ITS-managed configuration.
- After compiler changes, run the real native-contract freshness test; printing the stored fingerprint is not a freshness check.

---

## File Map

- Create marcedit_web/lib/external_task_parser.py for strict typed parsing and provenance.
- Create marcedit_web/lib/external_field_syntax.py for mnemonic fields, source references, and reviewed Leader conditions.
- Create marcedit_web/lib/field_predicates.py for reusable indicator and subfield selection.
- Modify marcedit_web/lib/external_task_migration.py for adapters, ordered expansions, and suggestions.
- Modify marcedit_web/lib/transforms.py, task_builder.py, and task_authoring.py for new structured behavior and shared preflight.
- Modify marcedit_web/render/task_authoring.py, task_operation_dialog.py, and tasks.py for authoring and import UX.
- Modify marcedit_web/lib/native_tasks.py to reject runnable blocker exports.
- Create marcedit_web/schemas/external-task-compatibility-v1.json.
- Create scripts/audit_external_task_corpus.py.
- Create sanitized fixtures under tests/fixtures/external_task_migration.
- Extend the focused tests named below.

---

### Task 1: Typed Parser and Compatibility Contract Schema

**Files:**
- Create: marcedit_web/lib/external_task_parser.py
- Create: marcedit_web/schemas/external-task-compatibility-v1.json
- Create: tests/fixtures/external_task_migration/parser-shapes.tasksfile.txt
- Create: tests/test_external_task_parser.py
- Modify: tests/test_external_task_migration.py

**Interfaces:**
- Produces ExternalInstruction, ExternalParseError, parse_instruction(source_line, source_entry="", line_number=0), and instruction_shape(value).
- Produces manifest schema version 1 and validates only the adapter entries
  registered by the end of this task. Tasks 3–6 append and verify their own
  adapter rows; Task 10 enforces complete corpus coverage.

- [ ] **Step 1: Write strict parser tests**

~~~python
def test_parse_add_preserves_empty_condition_and_provenance():
    item = parse_instruction(
        "ADD\t506\t1\\$aAccess.$5ABC\t100\t",
        source_entry="core.tasksfile.txt",
        line_number=7,
    )
    assert item.verb == "ADD"
    assert item.arguments == ("506", "1\\$aAccess.$5ABC", "100", "")
    assert item.option_code == 100
    assert (item.source_entry, item.line_number) == ("core.tasksfile.txt", 7)
    assert len(item.instruction_sha256) == 64


def test_parse_rejects_non_boolean_build_flag():
    with pytest.raises(ExternalParseError, match="Build Field flag 3"):
        parse_instruction(
            "buildnewfield\t=035  9\\$a{001}\tFalse\tFalse\tmaybe\tFalse"
        )
~~~

Test every verb’s required column count, numeric options, Boolean options, empty columns, malformed values, CRLF normalization, and nonempty surplus columns.

- [ ] **Step 2: Run RED**

Run: docker compose run --rm marcedit-web pytest tests/test_external_task_parser.py -q

Expected: collection fails because the parser module does not exist.

- [ ] **Step 3: Implement the immutable parsed value and strict decoders**

~~~python
@dataclass(frozen=True)
class ExternalInstruction:
    verb: str
    arguments: tuple[str, ...]
    source_line: str
    source_entry: str
    line_number: int
    instruction_sha256: str
    option_code: int | None = None
    boolean_flags: tuple[bool, ...] = ()


def parse_instruction(source_line: str, *, source_entry: str = "", line_number: int = 0) -> ExternalInstruction:
    parts = source_line.rstrip("\r\n").split("\t")
    if not parts or not parts[0].strip():
        raise ExternalParseError("instruction verb is required")
    verb = parts[0].strip()
    arguments = tuple(parts[1:])
    option_code, boolean_flags = _decode_options(verb, arguments)
    normalized = source_line.rstrip("\r\n")
    return ExternalInstruction(
        verb=verb,
        arguments=arguments,
        source_line=normalized,
        source_entry=source_entry,
        line_number=line_number,
        instruction_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        option_code=option_code,
        boolean_flags=boolean_flags,
    )
~~~

- [ ] **Step 4: Add the manifest and a non-vacuous freshness test**

Manifest entries use this shape:

~~~json
{
  "schema_version": 1,
  "adapters": [
    {
      "adapter_id": "subfield-edit-v1",
      "verbs": ["SUBFIELD_EDIT"],
      "shape_ids": ["subfield-edit-literal"],
      "fixture_ids": ["subfield-edit-literal"]
    }
  ]
}
~~~

Assert every entry currently listed has a registered adapter and an exercised
fixture. Do not list future adapters merely to reserve their names. Unknown
schema versions fail closed.

- [ ] **Step 5: Run GREEN and commit**

Run: docker compose run --rm marcedit-web pytest tests/test_external_task_parser.py tests/test_external_task_migration.py -q

Expected: all pass with zero skips.

Commit:

~~~bash
git add marcedit_web/lib/external_task_parser.py marcedit_web/schemas/external-task-compatibility-v1.json tests/fixtures/external_task_migration/parser-shapes.tasksfile.txt tests/test_external_task_parser.py tests/test_external_task_migration.py
git commit -m "feat: parse external task instructions strictly"
~~~

---

### Task 2: External Field Syntax and Build Field References

**Files:**
- Create: marcedit_web/lib/external_field_syntax.py
- Modify: marcedit_web/lib/task_authoring.py
- Modify: marcedit_web/lib/task_builder.py
- Modify: marcedit_web/render/task_authoring.py
- Create: tests/test_external_field_syntax.py
- Modify: tests/test_task_authoring.py
- Modify: tests/test_task_operation_dialog.py

**Interfaces:**
- Produces parse_mnemonic_field(value), parse_build_template(value), and parse_leader_condition(value).
- Extends Build Field segments with data_subfield segments containing tag and code.
- Consumes existing Add/Build mutation policies.

- [ ] **Step 1: Write exact corpus-template tests**

~~~python
def test_control_and_data_references_parse_in_order():
    parsed = parse_build_template(
        "=856  40$uhttps://proxy/?url={857$u}$yLink to resource"
    )
    assert parsed["tag"] == "856"
    assert parsed["ind1"] == "4"
    assert parsed["ind2"] == "0"
    assert parsed["structured_subfields"][0][0] == "u"
    assert parsed["structured_subfields"][0][1][-1] == {
        "type": "data_subfield", "tag": "857", "code": "u"
    }


@pytest.mark.parametrize(
    "template",
    [
        "=035  9\\$a({003}){001}",
        "=876  \\\\$aB({003}){001}-SC$lInternet",
        "=852  0\\$h{050$a} {050$b}$lONLINE",
    ],
)
def test_corpus_templates_round_trip_without_text_loss(template):
    assert render_external_field(parse_build_template(template)) == template
~~~

Add failures for malformed tags, incomplete dollar markers, literal braces, functions, and [x] multi-field tokens.

- [ ] **Step 2: Run RED**

Run: docker compose run --rm marcedit-web pytest tests/test_external_field_syntax.py tests/test_task_authoring.py -q

Expected: missing module and unsupported data_subfield segments.

- [ ] **Step 3: Implement field parsing and data-subfield execution**

ParsedField contains tag, indicators, and ordered subfield/segment values. Backslash becomes blank only in indicator positions.

Add a deterministic helper:

~~~python
def first_subfield_value(record, tag: str, code: str) -> str | None:
    field = record.get(tag)
    if field is None:
        return None
    values = field.get_subfields(code)
    return values[0] if values else None
~~~

Data-subfield and control-field sources share the existing missing-source policy. Preserve legacy stored parameter names while changing the UI label to “Missing source value.”

- [ ] **Step 4: Add segment controls and save/reopen tests**

Render Text, Control field, and Data subfield choices with keys shaped as op_0_sf_1_seg_2. Test Add, move, remove, Cancel, Save, mnemonic rendering, and lossless reopen.

- [ ] **Step 5: Run GREEN and compiler guards**

Run:

~~~bash
docker compose run --rm marcedit-web pytest tests/test_external_field_syntax.py tests/test_task_authoring.py tests/test_task_operation_dialog.py tests/test_codegen_safety.py -q
docker compose run --rm marcedit-web pytest tests/test_native_task_contract.py::test_checked_in_contract_matches_every_golden_definition -q
~~~

Update the checked-in compiler manifest only through its generator and inspect any diff.

- [ ] **Step 6: Commit**

~~~bash
git add marcedit_web/lib/external_field_syntax.py marcedit_web/lib/task_authoring.py marcedit_web/lib/task_builder.py marcedit_web/render/task_authoring.py tests/test_external_field_syntax.py tests/test_task_authoring.py tests/test_task_operation_dialog.py marcedit_web/schemas/native-task-compiler-contract-v1.json
git commit -m "feat: support open field template references"
~~~

---

### Task 3: Core DELETE, ADD, Build, RDA, and SORT Adapters

**Files:**
- Modify: marcedit_web/lib/external_task_migration.py
- Modify: marcedit_web/lib/rda_operations.py
- Create: tests/fixtures/external_task_migration/core-automatic.tasksfile.txt
- Modify: tests/test_external_task_migration.py
- Modify: tests/test_rda_operations.py

**Interfaces:**
- Produces adapters delete-v1, add-v1, build-field-v1, rda-smith-open-v1, and sort-all-v1.
- Changes MigrationItem to ordered operations; retain a read-only singular operation compatibility accessor for one release.

- [ ] **Step 1: Write option-policy tests**

~~~python
@pytest.mark.parametrize(
    ("line", "policy"),
    [
        ("ADD\t506\t1\\$aAccess.$5ABC\t100\t", "append"),
        ("ADD\t050\t\\\\$aOnline\t101\t", "skip_if_tag_exists"),
        ("ADD\t336\t\\\\$atext$btxt$2rdacontent\t108\t", "skip_if_identical"),
    ],
)
def test_add_codes_become_named_policies(line, policy):
    item = adapt_instruction(line)
    assert item.status == "converted"
    assert item.operations[0]["params"]["existing_field_action"] == policy
~~~

Cover exact and wildcard DELETE, all reviewed Leader conditions, both corpus Build Field flag combinations, and SORTBY ALL True True. Assert unknown flags decline with a suggestion.

- [ ] **Step 2: Write the approved RDA replacement test**

~~~python
def test_corpus_rda_signature_expands_to_visible_open_equivalent():
    item = adapt_instruction(
        "RDAHELPER\t1|1|0|0|0|0|0|0|0|0|0|0|0|0|0|0|language of cataloging|0"
    )
    assert [op["kind"] for op in item.operations] == ["rda-classify-material"]
    assert item.disclosure == (
        "Smith open equivalent; not a byte-for-byte external emulation"
    )
~~~

- [ ] **Step 3: Run RED**

Run: docker compose run --rm marcedit-web pytest tests/test_external_task_migration.py tests/test_rda_operations.py -q

Expected: current registry leaves these families unresolved.

- [ ] **Step 4: Implement exact adapters and safe near-miss suggestions**

A decline returns structured intent, reason, recommended operation, prefilled parameters, and a concrete cataloger action. Never normalize an unknown option to the nearest supported value.

- [ ] **Step 5: Prove cataloging effects**

Compile and run representative converted operations against MARC records covering missing sources, existing tags, identical fields, matching/nonmatching Leaders, and ambiguous RDA classification. Compare complete field lists.

- [ ] **Step 6: Run GREEN and commit**

Run: docker compose run --rm marcedit-web pytest tests/test_external_task_parser.py tests/test_external_task_migration.py tests/test_rda_operations.py tests/test_task_authoring.py -q

Commit:

~~~bash
git add marcedit_web/lib/external_task_migration.py marcedit_web/lib/rda_operations.py tests/test_external_task_migration.py tests/test_rda_operations.py tests/fixtures/external_task_migration/core-automatic.tasksfile.txt
git commit -m "feat: convert proven core task instructions"
~~~

---

### Task 4: Guided Subfield and Removal Adapters

**Files:**
- Modify: marcedit_web/lib/external_task_migration.py
- Modify: marcedit_web/lib/task_authoring.py
- Create: tests/fixtures/external_task_migration/subfield-operations.tasksfile.txt
- Modify: tests/test_external_task_migration.py
- Modify: tests/test_guided_replace.py
- Modify: tests/test_guided_replace_validation.py

**Interfaces:**
- Produces subfield-edit-v2 and subfield-remove-v1.
- Consumes guided-find-replace, empty-find-subfield-policy, and delete-subfield-if-value.

- [ ] **Step 1: Write special-form tests**

~~~python
@pytest.mark.parametrize(
    ("find", "replacement", "mode"),
    [
        ("Old", "New", "matched_text"),
        ("^b", "https://proxy/", "prepend"),
        ("^e", "eb", "append"),
    ],
)
def test_subfield_special_forms_convert(find, replacement, mode):
    item = adapt_instruction(
        f"SUBFIELD_EDIT\t856\tu\t{find}\t{replacement}\t0|0"
    )
    assert item.operations[0]["params"]["replacement_mode"] == mode


def test_empty_find_101_adds_only_when_missing():
    item = adapt_instruction(
        "SUBFIELD_EDIT\t856\ty\t\tLink to resource\t101|0"
    )
    assert item.operations[0]["params"]["policy"] == "add_if_missing"
~~~

- [ ] **Step 2: Add multiple-field behavioral tests**

Prove prepend/append affects the same selected values as the external option, does not create a missing source subfield, and option 101 adds only where the requested subfield is missing.

- [ ] **Step 3: Characterize SUBFIELD_REMOVE 107|0 before its adapter**

Use matching/nonmatching and repeated 035 $z values. The expected structured behavior removes only matching subfields and preserves the field and all other subfields. If local-package evidence contradicts this, stop and amend the approved design instead of guessing.

- [ ] **Step 4: Run RED, implement, and run GREEN**

Run before and after: docker compose run --rm marcedit-web pytest tests/test_external_task_migration.py tests/test_guided_replace.py tests/test_guided_replace_validation.py -q

Expected after: all pass; unsupported caret, pipe-move, or option shapes return a prefilled guided-operation blocker.

- [ ] **Step 5: Commit**

~~~bash
git add marcedit_web/lib/external_task_migration.py marcedit_web/lib/task_authoring.py tests/test_external_task_migration.py tests/test_guided_replace.py tests/test_guided_replace_validation.py tests/fixtures/external_task_migration/subfield-operations.tasksfile.txt
git commit -m "feat: migrate guided subfield instructions"
~~~

---

### Task 5: Field Predicates, Filtered Copy, and Matched Delete

**Files:**
- Create: marcedit_web/lib/field_predicates.py
- Modify: marcedit_web/lib/transforms.py
- Modify: marcedit_web/lib/task_builder.py
- Modify: marcedit_web/lib/task_authoring.py
- Modify: marcedit_web/render/task_authoring.py
- Modify: marcedit_web/lib/external_task_migration.py
- Create: tests/test_field_predicates.py
- Modify: tests/test_operations.py
- Modify: tests/test_task_authoring.py
- Modify: tests/test_external_task_migration.py

**Interfaces:**
- Produces validate_field_predicate(value) and field_matches(field, predicate).
- Predicate keys are ind1, ind2, ind1_not, ind2_not, and subfield_matches entries with code, mode, value, and ignore_case.
- Extends copy-field and matched-delete operations with optional predicate.

- [ ] **Step 1: Write predicate truth-table tests**

~~~python
@pytest.mark.parametrize(
    ("predicate", "expected"),
    [
        ({"ind1": "4", "ind2_not": "0"}, True),
        ({"ind1": "4", "ind2": "0"}, False),
        ({"subfield_matches": [{"code": "3", "mode": "contains", "value": "JSTOR", "ignore_case": False}]}, True),
    ],
)
def test_predicates_match_fields_without_serializing_mrk(predicate, expected):
    field = Field(
        tag="856",
        indicators=["4", "1"],
        subfields=[Subfield("3", "JSTOR collection")],
    )
    assert field_matches(field, predicate) is expected
~~~

Reject contradictory indicators, malformed subfield codes, empty match values, unknown modes, and indicator/subfield predicates on control fields.

- [ ] **Step 2: Write filtered-copy and matched-delete tests**

Prove COPY 856 to 857 limited by $3 containing JSTOR preserves the source, indicators, subfields, and order. Prove mnemonic field filters remove only selected fields.

Assert the COPY and matched DELETE adapters emit those predicate-aware
operations, and that a changed filter flag becomes a prefilled blocker rather
than an unfiltered operation.

- [ ] **Step 3: Run RED**

Run: docker compose run --rm marcedit-web pytest tests/test_field_predicates.py tests/test_operations.py tests/test_task_authoring.py tests/test_external_task_migration.py -q

- [ ] **Step 4: Implement the leaf predicate engine and safe compiler output**

field_predicates.py imports only stdlib and pymarc. Re-export predicate-aware transforms at the bottom of transforms.py. Emit the complete predicate through data_lit(); repr(dict(params)) is forbidden.

- [ ] **Step 5: Add optional guided controls and descriptions**

Render “Limit which fields are affected” with indicator and subfield rows. A summary must say, for example, “Copy 856 to 857 only when $3 contains JSTOR.”

- [ ] **Step 6: Run GREEN and commit**

Run: docker compose run --rm marcedit-web pytest tests/test_field_predicates.py tests/test_operations.py tests/test_task_authoring.py tests/test_external_task_migration.py tests/test_codegen_safety.py tests/test_native_task_contract.py -q

Commit:

~~~bash
git add marcedit_web/lib/field_predicates.py marcedit_web/lib/transforms.py marcedit_web/lib/task_builder.py marcedit_web/lib/task_authoring.py marcedit_web/lib/external_task_migration.py marcedit_web/render/task_authoring.py tests/test_field_predicates.py tests/test_operations.py tests/test_task_authoring.py tests/test_external_task_migration.py marcedit_web/schemas/native-task-compiler-contract-v1.json
git commit -m "feat: add structured field predicates"
~~~

---

### Task 6: Structural REPLACE and Control-Field Adapters

**Files:**
- Modify: marcedit_web/lib/structural_replace.py
- Modify: marcedit_web/lib/transforms.py
- Modify: marcedit_web/lib/task_builder.py
- Modify: marcedit_web/lib/external_task_migration.py
- Create: tests/fixtures/external_task_migration/replace-signatures.tasksfile.txt
- Modify: tests/test_structural_replace.py
- Modify: tests/test_external_task_migration.py

**Interfaces:**
- Produces replace-corpus-v1 and edit-control-field-v1 adapters.
- Extends structural requests with the predicate from Task 5.
- Produces set-control-field parameters: tag, mode, value, and zero-based position for positional edits.

- [ ] **Step 1: Write exact signature classification tests**

Cover the two 008 “o” positions, the Ellis blank 008 position, 856 to temporary 956 and back, 336/337/338 complete-field normalizations, 035 prefix normalization, and 852 normalization. Change one column or flag in each case and assert it becomes a suggestion rather than a conversion.

Add the corpus EDITFIELD 001 signature to this table. It must either emit the
same set-control-field operation proven by its characterization fixture or
remain a prefilled blocker; it may not be silently classified as converted.

- [ ] **Step 2: Write 856 sequence-equivalence tests**

Build records with 856 indicators 40, 41, and a non-4 first indicator. Compare the original staged sequence’s intended output with a direct predicate-aware operation. Select the direct representation only if the complete matrix is equal.

- [ ] **Step 3: Run RED**

Run: docker compose run --rm marcedit-web pytest tests/test_structural_replace.py tests/test_external_task_migration.py -q

- [ ] **Step 4: Implement exact recognizers and set-control-field**

Every recognizer compares all source columns, delimiters, mode, condition, and flags. Positional edits validate field existence, index bounds, and one-character replacement; short fields skip and report rather than extend.

- [ ] **Step 5: Add execution and preservation tests**

Invalid positions, backreferences, malformed complete fields, and unknown regex signatures fail before execution. Assert unrelated fields and source order remain unchanged unless the explicit final sort operation runs.

- [ ] **Step 6: Run GREEN and commit**

Run: docker compose run --rm marcedit-web pytest tests/test_structural_replace.py tests/test_external_task_migration.py tests/test_operations.py tests/test_codegen_safety.py tests/test_native_task_contract.py -q

Commit:

~~~bash
git add marcedit_web/lib/structural_replace.py marcedit_web/lib/transforms.py marcedit_web/lib/task_builder.py marcedit_web/lib/external_task_migration.py tests/test_structural_replace.py tests/test_external_task_migration.py tests/fixtures/external_task_migration/replace-signatures.tasksfile.txt marcedit_web/schemas/native-task-compiler-contract-v1.json
git commit -m "feat: migrate structural replace instructions"
~~~

---

### Task 7: Migration Blocker Storage and Shared Preflight

**Files:**
- Modify: marcedit_web/lib/task_builder.py
- Modify: marcedit_web/lib/task_authoring.py
- Modify: marcedit_web/lib/native_tasks.py
- Modify: marcedit_web/render/tasks.py
- Modify: tests/test_task_authoring.py
- Modify: tests/test_native_tasks.py
- Modify: tests/test_tasks_workspace_modes.py

**Interfaces:**
- Produces migration_blockers(operations) and assert_runnable_operations(operations).
- Produces a draft-only migration-blocker operation marker.

- [ ] **Step 1: Write round-trip and non-execution tests**

~~~python
def test_blocker_round_trips_but_never_becomes_executable():
    blocker = Operation("migration-blocker", {
        "intent": "Edit control field 001",
        "reason": "Exact external mode is unproven",
        "suggestion": {
            "operation_kind": "set-control-field",
            "prefilled_params": {"tag": "001"},
        },
        "instruction_sha256": "a" * 64,
    })
    rendered = render_ops_to_python([blocker])
    reopened = parse_ops_from_source(rendered["body"])
    assert reopened["operations"][0].to_dict() == blocker.to_dict()
    with pytest.raises(ValueError, match="Resolve 1 imported instruction"):
        assert_runnable_operations([blocker.to_dict()])
~~~

The generated body may contain only the structured marker and inert explanatory comments.

- [ ] **Step 2: Write all-entry-point preflight tests**

Saving in form mode succeeds and labels the task “Needs migration review.” Per-operation preview, direct execution, queued submission, operation-runner reconstruction, and native runnable export all reject the same blocker. A historical unrelated comment must not trigger the gate.

- [ ] **Step 3: Run RED**

Run: docker compose run --rm marcedit-web pytest tests/test_task_authoring.py tests/test_native_tasks.py tests/test_tasks_workspace_modes.py -q

- [ ] **Step 4: Implement one marker-based preflight**

Normalize and validate required user-facing fields and the digest. Every runnable entry point calls assert_runnable_operations after parsing operations and before creating a TaskSpec. Do not pattern-match rendered source text.

- [ ] **Step 5: Run GREEN and commit**

Run: docker compose run --rm marcedit-web pytest tests/test_task_authoring.py tests/test_native_tasks.py tests/test_tasks_workspace_modes.py tests/test_codegen_safety.py -q

Commit:

~~~bash
git add marcedit_web/lib/task_builder.py marcedit_web/lib/task_authoring.py marcedit_web/lib/native_tasks.py marcedit_web/render/tasks.py tests/test_task_authoring.py tests/test_native_tasks.py tests/test_tasks_workspace_modes.py
git commit -m "feat: persist safe migration review drafts"
~~~

---

### Task 8: Archive Draft Construction and Direct Opening

**Files:**
- Modify: marcedit_web/lib/marcedit_import.py
- Modify: marcedit_web/lib/external_task_migration.py
- Modify: marcedit_web/render/tasks.py
- Modify: tests/test_marcedit_import.py
- Modify: tests/test_task_import_traversal.py
- Modify: tests/test_tasks_workspace_modes.py

**Interfaces:**
- Produces one MigrationDraft per archive entry with task_name, ordered operations, counts, disclosures, and provenance.
- Consumes all adapters and blocker markers from Tasks 1–7.

- [ ] **Step 1: Write full, partial, and mixed archive tests**

~~~python
def test_fully_converted_entry_returns_editable_draft(tmp_path):
    result = convert_task_archive(
        make_archive(tmp_path, {"core.tasksfile.txt": SANITIZED_FULLY_PROVEN})
    )
    entry = result.entries[0]
    assert entry.status == "draft_ready"
    assert entry.summary.blocking == 0


def test_partial_entry_preserves_blocker_order(tmp_path):
    result = convert_task_archive(
        make_archive(tmp_path, {"mixed.tasksfile.txt": MIXED_SOURCE})
    )
    assert [op["kind"] for op in result.entries[0].operations] == [
        "delete-tag", "migration-blocker", "sort-fields"
    ]
~~~

- [ ] **Step 2: Pin archive isolation and existing limits**

A blocked entry must not discard a valid sibling. Traversal, duplicate names, entry count, uncompressed-byte, and quota behavior must remain unchanged.

- [ ] **Step 3: Run RED**

Run: docker compose run --rm marcedit-web pytest tests/test_marcedit_import.py tests/test_task_import_traversal.py tests/test_tasks_workspace_modes.py -q

- [ ] **Step 4: Build drafts without writing tasks during parsing**

Adopt a single fully converted draft directly into K_EDITOR_OPS. Present an entry chooser for multi-task archives. Preserve TASK-187 diagnostics until explicit dismissal or adoption.

- [ ] **Step 5: Run GREEN and commit**

Run: docker compose run --rm marcedit-web pytest tests/test_marcedit_import.py tests/test_task_import_traversal.py tests/test_tasks_workspace_modes.py tests/test_codegen_safety.py -q

Commit:

~~~bash
git add marcedit_web/lib/marcedit_import.py marcedit_web/lib/external_task_migration.py marcedit_web/render/tasks.py tests/test_marcedit_import.py tests/test_task_import_traversal.py tests/test_tasks_workspace_modes.py
git commit -m "feat: open imported tasks as ordered drafts"
~~~

---

### Task 9: Cataloger Summary and Suggested-Operation Workflow

**Files:**
- Modify: marcedit_web/render/tasks.py
- Modify: marcedit_web/render/task_operation_dialog.py
- Modify: marcedit_web/render/task_authoring.py
- Modify: tests/test_tasks_workspace_modes.py
- Modify: tests/test_task_operation_dialog.py

**Interfaces:**
- Consumes MigrationDraft, MigrationSuggestion, and migration-blocker operations.
- Produces bounded summaries, technical expanders, and transactional suggested-operation dialogs.

- [ ] **Step 1: Write approved-copy hierarchy tests**

~~~python
def test_full_import_shows_summary_without_raw_diagnostics(fake_streamlit):
    render_import_draft(fully_converted_draft(count=18))
    assert "18 instructions converted" in fake_streamlit.visible_text
    assert "Instruction fingerprint" not in fake_streamlit.visible_text
    assert fake_streamlit.expander_labels == ["Technical details"]


def test_every_blocker_has_a_next_action(fake_streamlit):
    render_migration_blocker(blocker_with_suggestion())
    assert "What this appears to do" in fake_streamlit.visible_text
    assert "Recommended" in fake_streamlit.visible_text
    assert "Open suggested operation" in fake_streamlit.button_labels
~~~

- [ ] **Step 2: Write transactional suggestion tests**

Opening copies prefilled values into modal state. Save replaces exactly the original blocker at its current index. Cancel restores it byte-for-byte. Invalid prefilled values remain visible with field-specific errors.

- [ ] **Step 3: Run RED**

Run: docker compose run --rm marcedit-web pytest tests/test_tasks_workspace_modes.py tests/test_task_operation_dialog.py -q

- [ ] **Step 4: Implement cataloger-first rendering**

Primary terms are “Converted,” “Needs your confirmation,” and “Cannot yet be represented.” Keep “adapter,” “signature,” “digest,” and “unresolved” inside Technical details. Each blocker shows intent, reason, preservation warning, recommendation, and next action.

Use the existing large non-dismissible operation dialog. Do not nest dialogs; keep Operation Reference as a tab.

- [ ] **Step 5: Test rerun persistence and accessibility**

Assert summaries and blockers survive Streamlit reruns and save/reopen. Use digest-based widget keys. Render the operation selector and first setup control first in DOM order.

- [ ] **Step 6: Run GREEN and commit**

Run: docker compose run --rm marcedit-web pytest tests/test_tasks_workspace_modes.py tests/test_task_operation_dialog.py tests/test_task_authoring.py -q

Commit:

~~~bash
git add marcedit_web/render/tasks.py marcedit_web/render/task_operation_dialog.py marcedit_web/render/task_authoring.py tests/test_tasks_workspace_modes.py tests/test_task_operation_dialog.py
git commit -m "feat: guide catalogers through task migration"
~~~

---

### Task 10: Sanitized Corpus, Local Audit, and Documentation

**Files:**
- Create: sanitized task files under tests/fixtures/external_task_migration
- Create: scripts/audit_external_task_corpus.py
- Modify: tests/test_task_authoring_corpus.py
- Modify: docs/external-task-migration.md
- Modify: docs/task-authoring-syntax.md
- Modify: docs/operation-reference.md
- Modify: tests/test_operation_reference_registry.py
- Modify: marcedit_web/schemas/external-task-compatibility-v1.json

**Interfaces:**
- Produces python scripts/audit_external_task_corpus.py CORPUS_ROOT.
- Produces cataloger documentation for every automatic family and suggestion path.

- [ ] **Step 1: Add sanitized fixtures for every corpus shape**

Replace names, proxies, locations, and note text with neutral values while preserving verbs, column counts, options, conditions, template forms, and regex structures. Assert fixture shape IDs equal manifest shape IDs.

- [ ] **Step 2: Write the local audit test**

~~~python
def test_local_corpus_classifies_every_instruction(corpus_root):
    if not corpus_root.exists():
        pytest.skip(
            "local example-task corpus is absent; mount it read-only "
            "for the authoritative audit"
        )
    report = audit_corpus(corpus_root)
    assert report.unclassified == ()
    assert report.items_without_next_action == ()
~~~

- [ ] **Step 3: Implement the bounded audit report**

The report prints document, instruction, conversion, and blocker counts plus adapter ID and source location. Full institutional lines print only with an explicit --technical flag. Exit nonzero for an unclassified line or blocker without a suggestion.

Run: python scripts/audit_external_task_corpus.py "/Users/roconnell/Projects/work/marcedit-web/MarcEdit Tasks"

Expected: 18 documents and every instruction classified. Measure unique lines rather than hard-coding 109 forever.

- [ ] **Step 4: Rewrite cataloger documentation**

For each family document “Imports automatically,” “Needs confirmation,” and “What to do next.” Add MARC before/after examples for source references, filtered copy, indicator-limited 856 editing, control-field positions, and the RDA open replacement.

- [ ] **Step 5: Run fixture, reference, and audit tests**

~~~bash
docker compose run --rm -v "/Users/roconnell/Projects/work/marcedit-web/MarcEdit Tasks:/corpus:ro" marcedit-web pytest tests/test_task_authoring_corpus.py tests/test_operation_reference_registry.py -q
docker compose run --rm -v "/Users/roconnell/Projects/work/marcedit-web/MarcEdit Tasks:/corpus:ro" marcedit-web python scripts/audit_external_task_corpus.py /corpus
~~~

Expected: no failures; audit has zero unclassified items and zero blockers without suggestions. Report every skip.

- [ ] **Step 6: Commit**

~~~bash
git add tests/fixtures/external_task_migration scripts/audit_external_task_corpus.py tests/test_task_authoring_corpus.py docs/external-task-migration.md docs/task-authoring-syntax.md docs/operation-reference.md tests/test_operation_reference_registry.py marcedit_web/schemas/external-task-compatibility-v1.json
git commit -m "docs: publish external task migration coverage"
~~~

---

### Task 11: End-to-End Verification, Review, and Closure

**Files:**
- Modify: .tickets/TASK-190-smith-core-import-completeness.md
- Modify only when a failure exposes a TASK-190 defect: files already named in Tasks 1–10.

**Interfaces:**
- Consumes all TASK-190 components.
- Produces an evidence-backed completion checkpoint and no new feature behavior.

- [ ] **Step 1: Run focused mounted-source suites**

~~~bash
docker compose run --rm -v "$PWD:/app" marcedit-web pytest \
  tests/test_external_task_parser.py \
  tests/test_external_field_syntax.py \
  tests/test_external_task_migration.py \
  tests/test_field_predicates.py \
  tests/test_structural_replace.py \
  tests/test_task_authoring_corpus.py \
  tests/test_tasks_workspace_modes.py \
  tests/test_task_operation_dialog.py -q
~~~

Expected: zero failures. Report every skip by name and reason.

- [ ] **Step 2: Run the authoritative local audit**

~~~bash
docker compose run --rm \
  -v "$PWD:/app" \
  -v "/Users/roconnell/Projects/work/marcedit-web/MarcEdit Tasks:/corpus:ro" \
  marcedit-web python scripts/audit_external_task_corpus.py /corpus
~~~

Expected: all documents classified, every non-converted line has a suggestion, and no external instruction is executable.

- [ ] **Step 3: Run compiler and code-generation guards**

~~~bash
docker compose run --rm -v "$PWD:/app" marcedit-web pytest tests/test_codegen_safety.py tests/test_native_task_contract.py tests/test_native_task_storage.py -q
git diff --exit-code -- marcedit_web/schemas/native-task-compiler-contract-v1.json
git diff --exit-code -- marcedit_web/schemas/external-task-compatibility-v1.json
~~~

Expected: zero failures and no unexplained manifest drift.

- [ ] **Step 4: Run the complete mounted-source suite**

Run: docker compose run --rm -v "$PWD:/app" marcedit-web pytest -q

Record exact passed, failed, and skipped counts. List every skip category.

- [ ] **Step 5: Rebuild and run the runtime-image disclosure suite**

~~~bash
docker compose build marcedit-web
docker compose run --rm marcedit-web pytest -q
~~~

Record exact counts and identify repository-identity tests unavailable inside the image. Do not merge with an application or TASK-190 failure.

- [ ] **Step 6: Perform authenticated browser verification**

Import the SC FOLIO archive and at least one Ellis archive at http://localhost:8501. Verify direct opening, summary counts, RDA disclosure, source references, 856 behavior, blocker replacement, Cancel, save/reopen, run blocking, and collapsed Technical details. Record archive names and outcomes in the ticket.

- [ ] **Step 7: Request independent review and remediate findings**

Review the full range from design commit 5b39db2 through implementation head. Fix every Critical or Important finding with a focused regression test and separate remediation commit. Re-run Steps 1–5.

- [ ] **Step 8: Mark TASK-190 Completed and commit**

Only after tests, audit, browser verification, and review are complete, record exact test counts, skip disclosure, corpus counts, review result, and commit range.

~~~bash
git add .tickets/TASK-190-smith-core-import-completeness.md
git commit -m "docs: complete TASK-190 importer coverage"
~~~
