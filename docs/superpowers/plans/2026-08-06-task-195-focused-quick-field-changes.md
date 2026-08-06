# TASK-195 Focused Quick Field Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Ticket:** [TASK-195](../../../.tickets/TASK-195-focused-quick-field-changes.md)

**Goal:** Add nine preview-first, one-operation Quick field changes with deterministic filter-then-occurrence selection, bounded sandbox execution, and recoverable application to Quick Load and job files.

**Architecture:** Keep selector and one-record mutation semantics in pure pymarc modules. Send every Common field change through a new allowlisted structured-adapter envelope in the existing subprocess sandbox; request values remain canonical JSON data and never become executable source. Put Streamlit controls in a dedicated renderer, while `render/tasks.py` supplies the existing loaded-file, job-version, snapshot, audit, and export integration.

**Tech Stack:** Python 3.9, pymarc, Streamlit 1.50, existing `RecordStore`, subprocess sandbox, SQLite job-file versions, pytest, Docker Compose.

## Global Constraints

- Ticket status becomes `In-Progress` only when implementation begins and `Completed` only after the full verification and code-review gates pass.
- One Common field change is allowed per Preview and Apply cycle; nothing is saved in the task library.
- Guided matching is the default. Raw regex is optional and never compiles or executes in the Streamlit process.
- Every Common field change executes through the same fixed child-side adapter for Preview and Apply preparation.
- Adapter payloads are bounded canonical JSON and mutually exclusive with executable task bodies.
- Each matcher is limited to 1,024 characters/2,048 bytes; the complete adapter payload is limited to 65,536 characters/131,072 bytes.
- No Common field change enters `OPERATIONS_PALETTE`, AI-draft validation, the Gemini prompt, external-task migration, or generated task Python.
- Missing First, Last, or Numbered occurrences skip the affected record; the engine never substitutes another occurrence.
- Apply reruns the exact canonical request against the current complete source, verifies source identity and record count, and adopts no partial output.
- Existing Quick Batch and Quick Find/Replace behavior remains unchanged.
- Supported runtime is Python 3.9; add no dependency.

---

### Task 1: Implement the Pure Filter-Then-Occurrence Selector

**Files:**
- Create: `marcedit_web/lib/quick_field_selector.py`
- Create: `tests/test_quick_field_selector.py`

**Interfaces:**
- Consumes: `pymarc.Record`, `pymarc.Field`.
- Produces: `IndicatorFilter`, `FieldFilter`, `Occurrence`, `FieldSelector`, `validate_field_filter()`, `validate_selector()`, `matching_fields()`, `resolve_fields()`, and `describe_selector()`.

- [ ] **Step 1: Mark the ticket In-Progress and write selector RED tests**

Update the ticket status, then add table-driven tests that construct records with zero, one, two, and three `856` or `070` fields. Pin exact-tag filtering, Any/MARC-blank/exact indicators, Exact/Contains/Starts-with/Ends-with text, case choice, and First/Last/Every/Numbered selection.

```python
def test_filter_then_occurrence_numbers_only_filtered_fields():
    record = _record(
        _field("856", "4", "0", ("u", "https://other.example/a")),
        _field("856", "4", "0", ("u", "https://kanopy.com/one")),
        _field("856", "4", "0", ("u", "https://kanopy.com/two")),
    )
    selector = FieldSelector(
        field_filter=FieldFilter(
            tag="856",
            subfield_code="u",
            match_mode="contains",
            match_value="kanopy.com",
        ),
        occurrence=Occurrence(mode="numbered", number=2),
    )

    result = resolve_fields(record, selector)

    assert result.fields == (record.fields[2],)
    assert result.skip_reason is None
```

Also pin these WHY cases: numbered occurrence is bounded to 1–999; control fields reject indicators/subfields; `000` is rejected; Every is rejected when `allow_every=False`; absent occurrences return stable reason codes (`no-filtered-fields`, `numbered-occurrence-absent`) instead of raising.

- [ ] **Step 2: Run the selector tests and confirm RED**

Run: `pytest -q tests/test_quick_field_selector.py`

Expected: collection fails because `quick_field_selector` does not exist.

- [ ] **Step 3: Implement immutable selector values and deterministic resolution**

Use these public shapes:

```python
@dataclass(frozen=True)
class IndicatorFilter:
    mode: str = "any"       # any | blank | exact
    value: str = ""

@dataclass(frozen=True)
class FieldFilter:
    tag: str
    ind1: IndicatorFilter = IndicatorFilter()
    ind2: IndicatorFilter = IndicatorFilter()
    subfield_code: str = ""
    match_mode: str = "exact"  # exact | contains | starts_with | ends_with | raw_regex
    match_value: str = ""
    ignore_case: bool = False

@dataclass(frozen=True)
class Occurrence:
    mode: str = "first"     # first | last | every | numbered
    number: int | None = None

@dataclass(frozen=True)
class FieldSelector:
    field_filter: FieldFilter
    occurrence: Occurrence = Occurrence()

@dataclass(frozen=True)
class SelectionResult:
    fields: tuple[pymarc.Field, ...]
    skip_reason: str | None = None
```

Normalize tag and subfield code once. Preserve record order. Compile raw regex only inside `matching_fields()`; production callers reach that function only in the sandbox. Validation returns cataloger-facing errors and resolution returns stable machine reason codes.

- [ ] **Step 4: Run selector tests GREEN**

Run: `pytest -q tests/test_quick_field_selector.py`

Expected: all pass, zero skipped.

- [ ] **Step 5: Commit the selector checkpoint**

```bash
git add .tickets/TASK-195-focused-quick-field-changes.md marcedit_web/lib/quick_field_selector.py tests/test_quick_field_selector.py
git commit -m "feat: add quick field selector"
```

---

### Task 2: Implement the Nine One-Record Mutations

**Files:**
- Create: `marcedit_web/lib/quick_field_changes.py`
- Create: `tests/test_quick_field_changes.py`
- Modify: `tests/test_transforms.py`

**Interfaces:**
- Consumes: Task 1 selector types and existing helpers in `marcedit_web.lib.transforms`.
- Produces: `QuickFieldChangeRequest`, `RecordChangeResult`, `validate_request()`, `request_to_payload()`, `request_from_payload()`, `apply_quick_field_change()`, and `prepare_quick_field_change_adapter()`.

- [ ] **Step 1: Write the operation-matrix RED tests**

Use one immutable request shape with operation-specific fields defaulted to empty values:

```python
@dataclass(frozen=True)
class QuickFieldChangeRequest:
    kind: str
    selector: FieldSelector | None = None
    second_selector: FieldSelector | None = None
    duplicate_filter: FieldFilter | None = None
    destination_tag: str = ""
    control_value: str = ""
    ind1: str | None = None
    ind2: str | None = None
    subfields: tuple[tuple[str, str], ...] = ()
    subfield_code: str = ""
    subfield_value: str = ""
    position: str = "append"
    repeat_policy: str = "append"
    record_scope: str = "every"
    destination_policy: str = "append"
    subfield_occurrence: str = "every"
    remove_empty_field: bool = False
    keep_duplicate: str = "first"
```

Add parameterized tests for the approved compatibility matrix. Every operation must cover changed, unchanged, record-skip, and request-invalid behavior. Pin these business cases:

- Add field supports control/data construction, tag-absent, and identical-field-absent policies.
- Add/Delete subfield affects only resolved fields and respects prepend/append, repeat policy, first/every matching subfield, and explicit empty-field removal.
- Copy never deletes destination fields until a source resolves; Replace-all is write-then-delete-safe.
- Move retags selected field objects in place and preserves source position.
- Set indicators distinguishes unchanged (`None`) from MARC blank (`" "`).
- Swap permits different filters on the same tag, rejects Every and identical selector definitions, and skips when two selectors resolve to the same object.
- Exact duplicate removal uses complete ordered MARC identity and stable keep-first/keep-last ordering.

```python
def test_swap_can_distinguish_same_tag_fields_by_filter():
    first = _field("070", " ", " ", ("a", "Kanopy feature"))
    second = _field("070", " ", " ", ("a", "Kanopy collection"))
    record = _record(first, second)
    request = _swap_request(
        first_filter="feature",
        first_occurrence="first",
        second_filter="collection",
        second_occurrence="first",
    )

    result = apply_quick_field_change(record, request)

    assert result.changed is True
    assert record.fields == [second, first]
```

- [ ] **Step 2: Run operation tests and confirm RED**

Run: `pytest -q tests/test_quick_field_changes.py`

Expected: collection fails because `quick_field_changes` does not exist.

- [ ] **Step 3: Implement validation, payload round-trip, and mutation**

Use a bounded result without MARC content:

```python
@dataclass(frozen=True)
class RecordChangeResult:
    changed: bool
    skipped: bool = False
    reason: str | None = None
    fields_affected: int = 0
    subfields_affected: int = 0

def prepare_quick_field_change_adapter(payload: object):
    request = request_from_payload(payload)
    errors = validate_request(request)
    if errors:
        raise ValueError("; ".join(errors))
    return lambda record: asdict(apply_quick_field_change(record, request))
```

Validate every enum fail-closed before mutation. Restrict Add field to at most 100 subfields. Validate source/destination control/data compatibility. Copy field objects deeply. Build all replacement candidates before deleting destination fields. Use object identity and list indexes for Swap.

- [ ] **Step 4: Add and pass shared-helper equivalence tests**

Compare the Quick result with the existing transform result for each exact overlap: data-field construction/identical suppression, unfiltered Every add-subfield, unfiltered Every append-copy, exact-tag Every deletion, exact/contains/raw-regex subfield deletion, unfiltered Every move, and unfiltered Every indicator changes. Add a negative test proving First never calls a whole-tag helper and leaves later fields untouched.

Run: `pytest -q tests/test_quick_field_changes.py tests/test_transforms.py`

Expected: all pass, zero skipped.

- [ ] **Step 5: Commit the mutation checkpoint**

```bash
git add marcedit_web/lib/quick_field_changes.py tests/test_quick_field_changes.py tests/test_transforms.py
git commit -m "feat: add focused quick field mutations"
```

---

### Task 3: Add the Structured Sandbox Adapter Envelope

**Files:**
- Modify: `marcedit_web/lib/sandbox.py`
- Modify: `tests/test_sandbox.py`

**Interfaces:**
- Consumes: Task 2 `prepare_quick_field_change_adapter(payload)`.
- Produces: `TaskSpec.adapter`, `TaskSpec.adapter_payload`, `SandboxResult.adapter_totals`, and child allowlist entry `quick-field-change`.

- [ ] **Step 1: Write sandbox-envelope RED tests**

Add tests proving:

```python
def test_structured_adapter_mutates_without_task_body(one_record_bytes):
    result = run_tasks_subprocess(
        [TaskSpec(
            name="quick-field-change",
            body="",
            adapter="quick-field-change",
            adapter_payload=_delete_245_payload(),
        )],
        one_record_bytes,
    )
    assert result.returncode == 0
    assert _read_output(result)[0].get_fields("245") == []
    assert result.adapter_totals["changed_records"] == 1
```

Also assert parent and child reject body+adapter, unknown adapters, non-JSON payloads, malformed operation payloads, and oversized payloads. Preserve the existing `test_noop_task_round_trips` body path unchanged. Add a parent-process spy proving no call to `re.compile` occurs while launching a raw-regex adapter.

- [ ] **Step 2: Run sandbox tests and confirm RED**

Run: `pytest -q tests/test_sandbox.py -k 'adapter or noop_task_round_trips'`

Expected: adapter tests fail because `TaskSpec` has no adapter fields.

- [ ] **Step 3: Implement the mutually exclusive request envelope**

Extend the dataclasses without changing existing positional construction:

```python
@dataclass
class TaskSpec:
    name: str
    body: str
    imports: list[str] = field(default_factory=list)
    capture_result: Optional[str] = None
    partner_batch_limits: dict[str, int] = field(default_factory=dict)
    adapter: Optional[str] = None
    adapter_payload: object = None

@dataclass
class SandboxResult:
    # existing fields remain unchanged
    adapter_totals: dict[str, object] = field(default_factory=dict)
```

In the parent serializer, call `task_preflight.assert_runnable_task_body()` only for body mode. Reject mixed mode. Add `MAX_ADAPTER_PAYLOAD_CHARS = 65_536` and `MAX_ADAPTER_PAYLOAD_BYTES = 131_072`; canonicalize with sorted compact JSON and reject either excess before launching the child. Keep the existing 1,024-character/2,048-byte matcher limit in the Quick request validator.

In `_DRIVER_SCRIPT`, use a literal allowlist—never `globals()`, `getattr()`, module paths, or operation names supplied by the request:

```python
_ADAPTER_PREPARERS = {
    "quick-field-change": quick_field_changes.prepare_quick_field_change_adapter,
}
```

Prepare and validate adapters once before record iteration. For every record, call the prepared adapter and aggregate only changed/unchanged/skipped records, fields/subfields affected, and at most 20 bounded reason codes. Keep original-record-on-error and output-cardinality behavior.

- [ ] **Step 4: Run the complete sandbox suite GREEN**

Run: `pytest -q tests/test_sandbox.py tests/test_task_preflight.py`

Expected: all pass, zero skipped on POSIX; if the existing Windows platform skip applies, report it explicitly rather than calling the run skip-free.

- [ ] **Step 5: Commit the sandbox checkpoint**

```bash
git add marcedit_web/lib/sandbox.py tests/test_sandbox.py
git commit -m "feat: add structured sandbox adapters"
```

---

### Task 4: Build Preview and Apply Candidates Through the Sandbox

**Files:**
- Create: `marcedit_web/lib/quick_field_change_runner.py`
- Create: `tests/test_quick_field_change_runner.py`

**Interfaces:**
- Consumes: `RecordStore`, Task 2 requests, Task 3 structured adapter mode, `task_diff.compute_task_diff()`.
- Produces: `QuickFieldChangePreview`, `QuickFieldChangeCandidate`, `build_preview(store, request, *, job_file_id=None, job_file_version_id=None, progress=None)`, `build_apply_candidate(store, preview, request, *, job_file_id=None, job_file_version_id=None, progress=None)`, `cleanup_artifact()`, and `adopt_candidate_to_store()`.

- [ ] **Step 1: Write runner RED tests**

Define the immutable request identity and disk-backed artifacts:

```python
@dataclass
class QuickFieldChangePreview:
    request: QuickFieldChangeRequest
    request_json: str
    output_path: Path | None = None
    workdir: Path | None = None
    record_count: int = 0
    changed_count: int = 0
    unchanged_count: int = 0
    skipped_count: int = 0
    fields_affected: int = 0
    subfields_affected: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)
    store_id: int | None = None
    store_revision: int | None = None
    job_file_id: int | None = None
    job_file_version_id: int | None = None
    error: str | None = None

@dataclass
class QuickFieldChangeCandidate:
    output_path: Path
    workdir: Path
    changed_count: int
    skipped_count: int
```

Tests must prove Preview uses adapter mode with an empty task body, retains bounded reason counts and representative diff evidence, and records store/job identities. Apply-candidate tests pass the currently rendered request separately and must prove the runner reruns the adapter, rejects a changed request/store/job version, detects output-cardinality mismatch, bounds timeout/cancellation/child errors, and leaves the store unchanged.

- [ ] **Step 2: Run runner tests and confirm RED**

Run: `pytest -q tests/test_quick_field_change_runner.py`

Expected: collection fails because the runner module does not exist.

- [ ] **Step 3: Implement preview construction and apply preparation**

`build_preview()` streams the full store to a temporary input, invokes one structured `TaskSpec`, verifies output cardinality, computes bounded diff evidence, and returns an error-state preview instead of adopting bytes. `build_apply_candidate()` canonicalizes its separate current-request argument and compares it with `preview.request_json`, then checks store identity/revision and supplied job IDs, reruns the exact adapter, verifies cardinality and aggregate counts, and returns a separately owned candidate.

`adopt_candidate_to_store()` calls `store.replace_from_path()` only after all checks pass. `cleanup_artifact()` removes only the workdir owned by the preview/candidate. No function mutates a job-file database row.

- [ ] **Step 4: Run runner, selector, mutation, and sandbox tests GREEN**

Run: `pytest -q tests/test_quick_field_change_runner.py tests/test_quick_field_selector.py tests/test_quick_field_changes.py tests/test_sandbox.py`

Expected: all pass; report any platform skips.

- [ ] **Step 5: Commit the runner checkpoint**

```bash
git add marcedit_web/lib/quick_field_change_runner.py tests/test_quick_field_change_runner.py
git commit -m "feat: sandbox quick field previews"
```

---

### Task 5: Add the Dedicated Common Field Changes Renderer

**Files:**
- Create: `marcedit_web/render/quick_field_changes.py`
- Create: `tests/test_quick_field_changes_render.py`

**Interfaces:**
- Consumes: Tasks 1–4 public request, selector, preview, and runner functions.
- Produces: `render_common_field_changes(store, *, job_file_id, job_file_version_id, on_apply)` where `on_apply(preview, current_request)` receives both values, plus stable session keys prefixed `quick_field_change_`.

- [ ] **Step 1: Write renderer RED tests with the existing Streamlit fake pattern**

Pin alphabetical labels exactly:

```python
EXPECTED_LABELS = [
    "Add field",
    "Add subfield",
    "Copy field",
    "Delete field",
    "Delete subfield",
    "Move or retag field",
    "Remove exact duplicate fields",
    "Set indicators",
    "Swap field occurrences",
]
```

Tests must assert that Add field and duplicate removal omit occurrence controls; Swap offers no Every; control tags remove indicator/subfield controls; the advanced regex control starts collapsed; Copy/Move show destination controls; Set indicators distinguishes Leave unchanged/MARC blank; and every-match shows the multi-field warning.

Add interaction tests proving Reset cleans the preview workdir and all `quick_field_change_` keys, changing any request widget makes the displayed preview stale, Preview errors stay visible, and Apply calls `on_apply(preview, current_request)` only for a current successful preview.

- [ ] **Step 2: Run renderer tests and confirm RED**

Run: `pytest -q tests/test_quick_field_changes_render.py`

Expected: collection fails because the renderer module does not exist.

- [ ] **Step 3: Implement operation-specific controls over shared selector controls**

Keep the renderer independent of `render/tasks.py`. Its public callable receives the store and adoption callback. Use one operation selectbox and one shared selector renderer; derive occurrence choices from a checked-in compatibility mapping matching the design table. Build `QuickFieldChangeRequest` only from explicit widgets. Render the summary before Preview and show metrics, bounded reason rows, representative MARC evidence, and collapsed record diffs after Preview.

The raw-regex widget only changes `FieldFilter.match_mode` to `raw_regex`; do not validate or compile it in the renderer. Preview delegates to `quick_field_change_runner.build_preview()`.

- [ ] **Step 4: Run renderer and engine tests GREEN**

Run: `pytest -q tests/test_quick_field_changes_render.py tests/test_quick_field_change_runner.py tests/test_quick_field_changes.py`

Expected: all pass, zero skipped.

- [ ] **Step 5: Commit the renderer checkpoint**

```bash
git add marcedit_web/render/quick_field_changes.py tests/test_quick_field_changes_render.py
git commit -m "feat: render common quick field changes"
```

---

### Task 6: Integrate Recoverable Job and Quick Load Application

**Files:**
- Modify: `marcedit_web/render/tasks.py` at `_render_quick_ops_mode` and the Quick Batch adoption helpers
- Modify: `tests/test_quick_batch.py`
- Create: `tests/test_task_quick_field_changes.py`

**Interfaces:**
- Consumes: Task 5 renderer callback and Task 4 `build_apply_candidate()`.
- Produces: `_apply_quick_field_change_preview(preview, current_request)`, job-file version source kind `quick-field-change`, Quick Load snapshot kind `quick-field-change`, audit event `quick-field-change-applied`, and disk-backed export evidence.

- [ ] **Step 1: Write integration RED tests**

Add tests that `_render_quick_ops_mode()` mounts Common field changes without changing existing Quick Find/Replace or Quick Batch labels. For job files, assert Apply reruns the adapter, passes an owned candidate to `session.adopt_current_candidate()`, records the current version as parent, and publishes summary data without MARC content.

For Quick Load, assert Apply stages the old store, adopts only the successful candidate, records a snapshot, creates the existing disk-backed download evidence, clears issue caches, and does not alter history on sandbox/adoption failure.

```python
def test_job_file_quick_field_change_creates_recoverable_version(monkeypatch):
    preview = _current_preview(job_file_id=10, job_file_version_id=100)
    adopted = []
    monkeypatch.setattr(
        tasks_render.session,
        "adopt_current_candidate",
        lambda **kwargs: adopted.append(kwargs) or {"version_number": 2},
    )

    tasks_render._apply_quick_field_change_preview(preview, preview.request)

    assert adopted[0]["source_kind"] == "quick-field-change"
    assert adopted[0]["summary"]["operation_kind"] == "swap-field-occurrences"
    assert "marc" not in str(adopted[0]["summary"]).lower()
```

Also pin stale store, stale job ID/version, cancellation, output mismatch, and candidate cleanup. Preserve the candidate until adoption has either committed or failed safely.

- [ ] **Step 2: Run integration tests and confirm RED**

Run: `pytest -q tests/test_task_quick_field_changes.py tests/test_quick_batch.py`

Expected: new integration tests fail because the renderer is not mounted and the apply callback does not exist; existing Quick Batch tests pass.

- [ ] **Step 3: Mount the renderer and implement the existing persistence boundaries**

Import `marcedit_web.render.quick_field_changes` and call it from `_render_quick_ops_mode()` between Quick Find/Replace and specialized Quick Batch. Pass current `job_file_id` and `job_file_version_id` only when `_uses_job_file_versions()` is true.

In `_apply_quick_field_change_preview()`, pass both the preview and current request to `build_apply_candidate()` first. Job mode passes the owned candidate to `session.adopt_current_candidate()` with a plain-language label and bounded summary. Quick Load mode wraps `adopt_candidate_to_store()` with `snapshot_actions.staged_store_path()` and `record_job_snapshot()`. Both modes emit the audit event, refresh download evidence, clear superseded previews, and rerun only after confirmed success.

- [ ] **Step 4: Run all Quick and persistence tests GREEN**

Run: `pytest -q tests/test_task_quick_field_changes.py tests/test_quick_field_changes_render.py tests/test_quick_batch.py tests/test_batch_replace.py tests/test_snapshot_actions.py tests/test_job_files.py`

Expected: all pass; report any existing platform skip explicitly.

- [ ] **Step 5: Commit the Tasks integration checkpoint**

```bash
git add marcedit_web/render/tasks.py tests/test_task_quick_field_changes.py tests/test_quick_batch.py
git commit -m "feat: apply quick field changes recoverably"
```

---

### Task 7: Document and Browser-Test the Cataloger Workflow

**Files:**
- Modify: `docs/operation-reference.md`
- Modify: `marcedit_web/lib/operation_reference.py`
- Modify: `tests/test_operation_reference_registry.py`
- Create: `tests/fixtures/quick-field-changes/multiple-070-and-856.mrc`

**Interfaces:**
- Consumes: completed UI and operation behavior.
- Produces: `QUICK_CHANGE_REFERENCE`, generated cataloger-facing Quick changes documentation/search entries, and a sanitized browser-acceptance fixture.

- [ ] **Step 1: Add a failing documentation freshness/coverage test**

Add a separate `QUICK_CHANGE_REFERENCE` mapping; do not add Quick kinds to `REFERENCE_REGISTRY`, whose exact task-palette contract remains unchanged. Require the generated Markdown and reference search to name all nine labels and explain: one-operation scope, filter-before-occurrence, First/Last/Numbered/Every, skip reasons, regex as optional advanced behavior, complete-field Swap, exact duplicate identity, and recoverable Preview/Apply.

Run: `pytest -q tests/test_operation_reference_registry.py -k 'quick or fresh'`

Expected: fails because the Quick changes section is absent.

- [ ] **Step 2: Write the cataloger reference and sanitized fixture**

Document worked examples for swapping two `070` fields and selecting one of multiple `856` fields by `$u`. Explain that Move/retag preserves source position and that Reorder fields is a separate explicit Quick action. Keep technical JSON, fingerprints, and Python out of the main guidance.

Create a small MARC fixture containing: two distinguishable `070` fields; three `856` fields with two matching one vendor; duplicate and near-duplicate `035` fields; a control field; and records missing requested occurrences.

- [ ] **Step 3: Run the reference test GREEN**

Run: `pytest -q tests/test_operation_reference_registry.py`

Expected: all pass; the repository-identity-file freshness test may skip only in the documented image-only environment and must be reported.

- [ ] **Step 4: Run browser acceptance in Docker**

Start the source-mounted application:

```bash
docker compose up -d --build marcedit-web
```

At `http://localhost:8501`, authenticate with the configured local Google account, upload the sanitized fixture, and verify:

1. Common field changes labels are alphabetical.
2. Delete field → `$u` contains filter → Numbered affects only the requested `856`.
3. Add subfield → Every shows a warning and affects every filtered `856`.
4. Swap exchanges the two selected `070` positions without changing their contents.
5. Missing occurrences are skipped and grouped by reason.
6. Invalid regex blocks Preview without crashing the page.
7. Reset removes preview evidence; changing a selector makes Apply unavailable until re-preview.
8. Quick Load Apply creates history/download evidence.
9. A shared-job file Apply creates a new version visible to collaborators.

Record the browser result in the TASK-195 completion checkpoint; do not mark the ticket complete yet.

- [ ] **Step 5: Commit documentation and fixtures**

```bash
git add docs/operation-reference.md marcedit_web/lib/operation_reference.py tests/test_operation_reference_registry.py tests/fixtures/quick-field-changes
git commit -m "docs: explain focused quick field changes"
```

---

### Task 8: Full Verification, Review, and Ticket Closure

**Files:**
- Modify: `.tickets/TASK-195-focused-quick-field-changes.md`
- Test: complete source-mounted and Docker suites

**Interfaces:**
- Consumes: all previous checkpoints.
- Produces: reviewed completion evidence and a `Completed` ticket only when every required gate passes.

- [ ] **Step 1: Run focused tests with no silent omissions**

```bash
pytest -q \
  tests/test_quick_field_selector.py \
  tests/test_quick_field_changes.py \
  tests/test_sandbox.py \
  tests/test_quick_field_change_runner.py \
  tests/test_quick_field_changes_render.py \
  tests/test_task_quick_field_changes.py \
  tests/test_quick_batch.py \
  tests/test_batch_replace.py \
  tests/test_operation_reference_registry.py
```

Record exact pass, fail, and skip counts. Investigate every skip; do not summarize a run with skips as simply “passing.”

- [ ] **Step 2: Run the full authoritative source-mounted suite**

Run: `pytest -q`

Expected: zero failures. Record all skips with their reasons.

- [ ] **Step 3: Run the Python 3.9 Docker suite**

```bash
docker compose run --rm --no-deps marcedit-web pytest -q
```

Record exact pass/fail/skip counts and distinguish mounted-source guarantees from image-only repository-file checks.

- [ ] **Step 4: Verify the task and AI boundaries**

Run:

```bash
pytest -q tests/test_task_builder.py tests/test_ai_task_draft.py tests/test_gemini_task_draft.py tests/test_external_task_migration.py
git diff --exit-code main -- marcedit_web/schemas/native-task-compiler-contract-v1.json
```

Expected: existing suites pass and the native compiler manifest is unchanged.

- [ ] **Step 5: Request code review and resolve findings**

Use `superpowers:requesting-code-review`. Review specifically for raw regex execution outside the child, body/adapter confusion, mutation before validation, stale preview adoption, job-version rollback, selector widening, unbounded diagnostics, and renderer leakage into `render/tasks.py`. Repeat focused and full verification after every material fix.

- [ ] **Step 6: Close the ticket and commit completion evidence**

Only after tests, browser acceptance, and review pass, set `Status: Completed` and record exact verification counts, browser scenarios, review disposition, and commit SHAs.

```bash
git add .tickets/TASK-195-focused-quick-field-changes.md
git commit -m "docs: complete TASK-195"
```

Do not push, merge, or include unrelated working-tree changes as part of ticket closure.
