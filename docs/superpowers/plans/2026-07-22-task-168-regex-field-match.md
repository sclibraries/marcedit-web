# TASK-168 Regex Field Match Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional `re.search` matching to replace-field-subfield-and-indicators while preserving existing exact saved tasks.

**Architecture:** Extend the transform with keyword-only `regex` and `ignore_case` flags defaulting false. The form builder validates enabled patterns before save, records additive marker keys, and emits the same helper call with explicit keyword flags.

**Tech Stack:** Python 3.9, `re`, pymarc 5, pytest, existing task-builder markers and Streamlit boolean parameter renderer.

## Global Constraints

- Ticket: [TASK-168](../../../.tickets/TASK-168-task-replace-field-regex-match.md).
- Exact, case-sensitive matching remains the default for old calls and markers.
- Regex mode uses `re.search`, not `fullmatch` or substitution.
- Replacement replaces the complete matched subfield value, as before.
- Invalid regex fails before persistence and before record mutation.
- Add no task kind and no dependency.

---

### Task 1: Extend transform matching safely

**Files:**
- Modify: `tests/test_transforms.py`
- Modify: `marcedit_web/lib/transforms.py`

**Interfaces:**
- Produces: `replace_field_subfield_and_indicators(record, tag, match_ind1, match_ind2, match_code, match_value, new_ind1, new_ind2, new_code, new_value, *, regex: bool = False, ignore_case: bool = False) -> None`.

- [ ] **Step 1: Add failing transform tests**

Add separate tests proving:

```python
transforms.replace_field_subfield_and_indicators(
    record, "035", " ", " ", "a", r"TFeba\d+",
    " ", "9", "a", "(SCTFEBA)", regex=True,
)
```

matches `prefix-TFeba123-suffix` via `re.search`; does not match
`prefix-tfeba123-suffix` by default; matches it with
`regex=True, ignore_case=True`; and leaves exact default behavior unchanged.

Add an invalid-pattern test:

```python
before = record.as_marc()
with pytest.raises(re.error):
    transforms.replace_field_subfield_and_indicators(
        record, "035", " ", " ", "a", "(",
        " ", "9", "a", "replacement", regex=True,
    )
assert record.as_marc() == before
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
python3 -m pytest tests/test_transforms.py -q
```

Expected: `TypeError` because the helper has no `regex` or `ignore_case` keyword.

- [ ] **Step 3: Implement compile-before-mutate matching**

Extend the signature with keyword-only defaults. Before iterating fields:

```python
flags = re.IGNORECASE if ignore_case else 0
pattern = re.compile(match_value, flags) if regex else None

def value_matches(value: str) -> bool:
    if pattern is not None:
        return pattern.search(value) is not None
    return value == match_value
```

Use `value_matches(subfield.value)` in the existing replacement loop.
`ignore_case` affects only compilation in regex mode; exact mode remains the
current case-sensitive equality behavior even if a hand-written caller passes
`ignore_case=True` without `regex=True`.

- [ ] **Step 4: Run transform tests and commit**

```bash
python3 -m pytest tests/test_transforms.py -q
python3 -m py_compile marcedit_web/lib/transforms.py
git diff --check
git add marcedit_web/lib/transforms.py tests/test_transforms.py
git commit -m "feat: support regex field matching"
```

### Task 2: Wire form schema, validation, and saved markers

**Files:**
- Modify: `tests/test_task_builder.py`
- Modify: `marcedit_web/lib/task_builder.py`
- Test: `marcedit_web/render/tasks.py`

**Interfaces:**
- Consumes: the Task 1 keyword flags.
- Produces: additive marker params `regex: bool` and `ignore_case: bool`.

- [ ] **Step 1: Add failing builder tests**

Extend the palette assertion to require these parameters after `match_value`:

```python
{"name": "regex", "label": "Treat match value as regex", "type": "bool", "default": False}
{"name": "ignore_case", "label": "Case-insensitive", "type": "bool", "default": False}
```

Add tests that generated code contains `regex=True, ignore_case=True`, new
markers round-trip both keys, an old marker without either key round-trips and
renders exact defaults, and `match_value="("` with `regex=True` raises
`ValueError` containing `invalid match regex`.

- [ ] **Step 2: Run builder tests and verify RED**

```bash
python3 -m pytest tests/test_task_builder.py -q
```

Expected: missing palette params/keywords and no invalid-regex `ValueError`.

- [ ] **Step 3: Add schema and validation**

Update the operation summary from “exact subfield value” to “subfield value
(exact or regex)”. Add the two boolean params shown above.

In `_render_one`, read defaults with:

```python
use_regex = bool(p.get("regex", False))
ignore_case = bool(p.get("ignore_case", False))
```

When regex is
enabled, validate before emitting code:

```python
try:
    re.compile(match_value, re.IGNORECASE if ignore_case else 0)
except re.error as exc:
    raise ValueError(f"invalid match regex: {exc}") from exc
```

Emit:

```python
replace_field_subfield_and_indicators(
    record, '035', ' ', ' ', 'a', 'TFeba', ' ', '9', 'a',
    '(SCTFEBA)', regex=True, ignore_case=True
)
```

using literal boolean values. Old parsed params omit the keys and render
`regex=False, ignore_case=False` without changing behavior.

- [ ] **Step 4: Run task-focused tests**

```bash
python3 -m pytest tests/test_task_builder.py tests/test_transforms.py tests/test_tasks.py tests/test_tasks_workspace_modes.py tests/test_note_task_draft.py -q
```

Expected: all runnable tests pass; list every skip by name and reason.

- [ ] **Step 5: Static checks and commit**

```bash
python3 -m py_compile marcedit_web/lib/task_builder.py marcedit_web/lib/transforms.py marcedit_web/render/tasks.py
git diff --check
git add marcedit_web/lib/task_builder.py tests/test_task_builder.py
git commit -m "feat: expose regex field match option"
```

### Task 3: Review and record TASK-168 evidence

**Files:**
- Modify: `.tickets/TASK-168-task-replace-field-regex-match.md`

- [ ] **Step 1: Request independent review**

Review backward compatibility, `re.search` semantics, invalid-pattern
atomicity, generated-code safety, marker round trips, and test intent. Resolve
every Critical and Important finding.

- [ ] **Step 2: Record evidence and commit**

Append exact test results, skips, hashes, static checks, and clean review
verdict; set `Status: Completed`, then commit:

```bash
git add .tickets/TASK-168-task-replace-field-regex-match.md
git commit -m "docs: complete TASK-168 evidence"
```
