# TASK-169 View Field-Order Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve source MARC order in View while warning about bounded adjacent tag inversions.

**Architecture:** Add a pure `viewer.field_order_inversions()` helper over `record.fields`; View renders a warning from that helper before rendering the unchanged record. No sorting, mutation, or serialization behavior changes.

**Tech Stack:** Python 3.9, pymarc 5, Streamlit, pytest.

## Global Constraints

- Ticket: [TASK-169](../../../.tickets/TASK-169-view-marc-field-order.md).
- View must preserve actual MARC directory order.
- Canonical diagnostic convention is ascending alphanumeric tag order.
- Equal adjacent tags are valid.
- Return and render at most 20 inversions.
- Do not mutate, sort, or rewrite the record.

---

### Task 1: Detect bounded adjacent inversions

**Files:**
- Modify: `tests/test_viewer.py`
- Modify: `marcedit_web/lib/viewer.py`

**Interfaces:**
- Produces: `field_order_inversions(record: Record, *, limit: int = 20) -> list[tuple[str, str]]`.

- [ ] **Step 1: Add failing helper tests**

Add this test helper, then build records with explicit field order:

```python
def record_with_tags(*tags):
    record = pymarc.Record()
    for tag in tags:
        if tag.startswith("00"):
            record.add_field(pymarc.Field(tag=tag, data=tag))
        else:
            record.add_field(
                pymarc.Field(
                    tag=tag,
                    indicators=[" ", " "],
                    subfields=[pymarc.Subfield("a", tag)],
                )
            )
    return record
```

Assert:

```python
assert viewer.field_order_inversions(record_with_tags("001", "008", "035", "040")) == []
assert viewer.field_order_inversions(record_with_tags("001", "040", "035", "245")) == [("040", "035")]
assert viewer.field_order_inversions(record_with_tags("035", "035", "040")) == []
assert len(viewer.field_order_inversions(many_inversions, limit=3)) == 3
```

Also capture `before = record.as_marc()` and assert it is identical after the
helper call.

- [ ] **Step 2: Run helper tests and verify RED**

```bash
python3 -m pytest tests/test_viewer.py -q
```

Expected: `AttributeError` because `field_order_inversions` does not exist.

- [ ] **Step 3: Implement the pure helper**

```python
def field_order_inversions(
    record: Record, *, limit: int = 20,
) -> list[tuple[str, str]]:
    """Return bounded adjacent descending tags without changing the record."""
    if limit <= 0:
        return []
    inversions: list[tuple[str, str]] = []
    for previous, current in zip(record.fields, record.fields[1:]):
        if current.tag < previous.tag:
            inversions.append((previous.tag, current.tag))
            if len(inversions) >= limit:
                break
    return inversions
```

- [ ] **Step 4: Prove rendering order remains unchanged**

Add a test with tags `001`, `040`, `035`, `245`; call
`viewer.render_record_human(record)` and assert the four line offsets remain in
that same order. Do not assert sorted output.

- [ ] **Step 5: Run and commit helper**

```bash
python3 -m pytest tests/test_viewer.py -q
python3 -m py_compile marcedit_web/lib/viewer.py
git diff --check
git add marcedit_web/lib/viewer.py tests/test_viewer.py
git commit -m "feat: detect MARC field order inversions"
```

### Task 2: Render the diagnostic in View

**Files:**
- Modify: `tests/test_view_render.py`
- Modify: `marcedit_web/render/view.py`

**Interfaces:**
- Consumes: `viewer.field_order_inversions(record, limit=20)`.
- Produces: one warning when inversions exist; no warning otherwise.

- [ ] **Step 1: Add a failing View contract test**

Add this source contract to `tests/test_view_render.py`:

```python
def test_view_warns_about_order_without_sorting_the_record():
    source = Path("marcedit_web/render/view.py").read_text()

    assert "viewer.field_order_inversions(record)" in source
    assert "st.warning(" in source
    assert "viewer.render_record_human(record, fields=tag_filter)" in source
    assert "sorted(record.fields" not in source
    assert "sort_fields(record" not in source
```

Import `Path` from `pathlib` at the top of the test module.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m pytest tests/test_view_render.py -q
```

Expected: failure because View does not call the inversion helper.

- [ ] **Step 3: Render one bounded warning**

Immediately before `viewer.render_record_human(...)`, add:

```python
inversions = viewer.field_order_inversions(record)
if inversions:
    transitions = ", ".join(
        f"{previous} before {current}" for previous, current in inversions
    )
    st.warning(
        "Fields are displayed in source order, but tag order decreases at: "
        + transitions
    )
```

Do not alter `record.fields`, `tag_filter`, or rendering.

- [ ] **Step 4: Run focused tests**

```bash
python3 -m pytest tests/test_viewer.py tests/test_view_render.py tests/test_view_edit.py -q
```

Expected: all pass; report every skip.

- [ ] **Step 5: Static checks and commit**

```bash
python3 -m py_compile marcedit_web/lib/viewer.py marcedit_web/render/view.py
git diff --check
git add marcedit_web/render/view.py tests/test_view_render.py
git commit -m "feat: warn on MARC field order inversions"
```

### Task 3: Review and record TASK-169 evidence

**Files:**
- Modify: `.tickets/TASK-169-view-marc-field-order.md`

- [ ] **Step 1: Request independent review**

Review source-order preservation, inversion definition, bounded output,
non-mutation, UI wording, and regression quality. Resolve every Critical and
Important finding.

- [ ] **Step 2: Record evidence and commit**

Append exact test results, skips, hashes, static checks, and clean review
verdict; set `Status: Completed`, then commit:

```bash
git add .tickets/TASK-169-view-marc-field-order.md
git commit -m "docs: complete TASK-169 evidence"
```

### Task 4: Final combined branch gate

**Files:**
- Modify only ticket evidence if verification changes recorded counts.

- [ ] **Step 1: Run combined focused suites**

```bash
python3 -m pytest tests/test_jobs.py tests/test_job_files.py tests/test_job_file_migration.py tests/test_job_file_workflow.py tests/test_job_file_mutations.py tests/test_task_builder.py tests/test_transforms.py tests/test_note_task_draft.py tests/test_viewer.py tests/test_view_render.py tests/test_view_edit.py -q
```

Expected: zero failures; report exact passes and every skip.

- [ ] **Step 2: Run complete Python 3.9 suite**

Run the repository in the existing Python 3.9 project image with this worktree
mounted read-only:

```bash
docker run --rm --network none \
  -v /Users/roconnell/Projects/work/marcedit-web/.worktrees/prod-fixes-task-167-170:/workspace:ro \
  -w /workspace -e PYTHONPATH=/workspace \
  marcedit-web:dev python -m pytest -q
```

Expected: zero failures; report exact passed/skipped counts and each skip name/reason.

- [ ] **Step 3: Run branch checks**

```bash
python3 -m compileall -q marcedit_web tests
git diff --check main...HEAD
git status --short
```

Expected: compile/diff clean and no uncommitted tracked changes.

- [ ] **Step 4: Request final whole-branch review**

Review `main...HEAD` against all four ticket specs and the approved design.
Resolve every Critical and Important finding, rerun affected focused suites,
then rerun `git diff --check main...HEAD`.

- [ ] **Step 5: Use superpowers:finishing-a-development-branch**

Present merge/cherry-pick/keep-worktree options. Do not merge, push, or deploy
without explicit user authorization.
