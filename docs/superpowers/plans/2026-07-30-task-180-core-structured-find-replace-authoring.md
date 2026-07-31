# Core Structured Find and Replace Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Ticket:** [TASK-180](../../../.tickets/TASK-180-structured-find-replace-authoring.md)

**Design:** [TASK-180 design](../specs/2026-07-30-task-180-structured-find-replace-authoring-design.md)

**Goal:** Let catalogers author, preview, save, reopen, and safely execute core control-field and subfield Find and Replace operations while preserving unmatched data by default.

**Architecture:** Add a leaf `guided_replace` engine with no `marcedit_web.lib` imports, then re-export its record transform through `transforms` so the existing compiler and sandbox contracts remain unchanged. Keep the existing form-task `# OP:` storage authoritative, add a dedicated Streamlit card and sandboxed first-record preview, and compose empty-find safety into TASK-179's submission preflight. Existing operation kinds, Quick Find/Replace, AI drafting, native tasks, storage, and deployment remain unchanged.

**Tech Stack:** Python 3.9, Streamlit 1.x, pymarc 5.x, pytest 8.x, existing task compiler and subprocess sandbox, SQLite task storage, and Docker Compose.

## Global Constraints

- Implement in an isolated worktree created with `superpowers:using-git-worktrees`; change TASK-180 from `Todo` to `In-Progress` only after the worktree exists.
- Follow [TASK-180's compatibility matrix](../specs/2026-07-30-task-180-structured-find-replace-authoring-design.md#compatibility-matrix) exactly. Do not add TASK-184 targets, actions, tag ranges, structured patterns, or named captures.
- Keep `guided_replace.py` a leaf module: it imports only the standard library and `pymarc`, and no `marcedit_web.lib` module.
- Use `match_mode="raw_regex"` as the only raw-regex storage discriminator. Do not add `use_regex`.
- Use `ignore_case`; do not introduce `case_sensitive`.
- Matched-text replacement is the new-operation default. Prepend and append have `match_mode="none"` and an empty stored `find`; other actions require a nonempty Find.
- Syntax and capture-reference errors block save. A current successful raw-regex preview blocks submission only, never save.
- Preserve every existing operation kind's compiler output and behavior. Do not normalize an old operation into `guided-find-replace`.
- Keep Quick Find/Replace implementation unchanged; use characterization tests to prove it.
- Keep deterministic note drafting, Gemini drafting, and AI validation behavior unchanged. The new palette kind must be excluded from both AI validation and Gemini's prompt schema.
- Keep TASK-178 native schema version 1 and `marcedit_web/schemas/native-task-compiler-contract-v1.json` unchanged.
- Do not change the database schema, worker, durable queue, services, Compose topology, routing, proxy, cron, deployment, or ITS files.
- Real files under `MarcEdit Tasks/` and real vendor records stay untracked and must not appear in commits, fixtures, screenshots, logs, or error text.
- Remain syntactically compatible with Python `>=3.9,<3.10`; use `Optional[...]` and `Tuple[...]` where runtime parsing requires it, and do not add `match` statements or `slots=True`.
- Use TDD for every behavior change: demonstrate the intended RED, implement the minimum GREEN, and run the focused regression set before each commit.
- Report every pytest skip and its reason. “Tests pass” is false when a skip is unreported.

---

## File Map

- Create `marcedit_web/lib/guided_replace.py`: leaf validation, matching, mutation, and JSON-safe result counts.
- Create `marcedit_web/lib/guided_replace_preview.py`: one-record sandbox preview, captured-result parsing, request/store staleness checks, and temporary-file cleanup.
- Modify `marcedit_web/lib/transforms.py`: import and re-export only `apply_guided_find_replace`.
- Modify `marcedit_web/lib/task_builder.py`: palette declaration and one compiler branch that assigns `_guided_replace_result`.
- Modify `marcedit_web/lib/task_authoring.py`: guided-operation validation, normalization, summaries, and composed submission preflight.
- Modify `marcedit_web/render/task_authoring.py`: progressive guided controls, plain-language explanation, preview button, and before/after display.
- Modify `marcedit_web/render/tasks.py`: delegate the new card, retain preview state, permit save without preview, and enforce current raw preview at submission.
- Modify `marcedit_web/lib/sandbox.py`: optional trusted result-variable capture for preview; existing callers receive an empty capture list.
- Modify `marcedit_web/lib/ai_task_draft.py`: expose and use one operation-support decision that rejects the new kind before parameter validation.
- Modify `marcedit_web/lib/gemini_task_draft.py`: omit operations rejected by the shared AI-support decision.
- Modify `marcedit_web/lib/marcedit_import.py`: classify empty-find `SUBFIELD_EDIT` as unresolved rather than executable.
- Modify `docs/task-authoring-syntax.md`: document core targets, match modes, replacement scopes, raw regex, and the 035 example.
- Create `tests/test_guided_replace.py`: complete engine compatibility-matrix coverage.
- Create `tests/test_guided_replace_preview.py`: sandbox capture, non-mutation, timeout/error, and staleness coverage.
- Modify `tests/test_task_builder.py`: palette, compiler, marker round-trip, and legacy characterization.
- Modify `tests/test_task_authoring.py`: normalization, validation, summaries, and submission-preflight coverage.
- Modify `tests/test_task_authoring_render.py`: progressive widget and preview-panel contracts.
- Modify `tests/test_tasks_workspace_modes.py`: default params, save-without-preview, preview retention, and submission gate integration.
- Modify `tests/test_tasks_export.py`: queued-run empty-find and raw-preview submission gates.
- Modify `tests/test_sandbox.py`: optional JSON-safe task-result capture and unchanged default result.
- Modify `tests/test_marcedit_import.py`: new empty-find refusal and unchanged nonempty import.
- Exercise unchanged `tests/test_task_import_traversal.py` and `tests/test_codegen_safety.py` as import/archive and code-generation safety regressions.
- Exercise unchanged `tests/test_batch_replace.py` and `tests/test_quick_replace_snapshot.py` as Quick Find/Replace characterization.
- Modify `tests/test_ai_task_draft.py` and `tests/test_gemini_task_draft.py`: explicit exclusion coverage.
- Exercise unchanged `tests/test_note_task_draft.py` as deterministic-draft characterization.
- Create `docs/superpowers/evidence/task-180-guided-find-replace-browser-smoke.md`: synthetic Docker/browser acceptance evidence.
- Modify `.tickets/TASK-180-structured-find-replace-authoring.md`: plan link, status, verification, commits, and review.
- Modify `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`: record the completed TASK-180 phase only after final acceptance.

---

### Task 1: Characterize legacy behavior and build the leaf engine

**Files:**
- Create: `marcedit_web/lib/guided_replace.py`
- Create: `tests/test_guided_replace.py`
- Modify: `tests/test_task_builder.py`
- Modify: `.tickets/TASK-180-structured-find-replace-authoring.md`

**Interfaces:**
- Produces: `TARGET_KINDS = ("control_field", "subfield", "all_subfields")`.
- Produces: `MATCH_MODES = ("contains", "starts_with", "ends_with", "whole_value", "raw_regex", "none")`.
- Produces: `REPLACEMENT_MODES = ("matched_text", "whole_value", "prepend", "append")`.
- Produces: `OCCURRENCE_MODES = ("first", "all")`.
- Produces: `validate_request(*, target_kind: str, tag: str, subfield: str, match_mode: str, find: str, ignore_case: bool, replacement_mode: str, replacement: str, occurrences: str) -> tuple[str, ...]`.
- Produces: `apply_guided_find_replace(record: Record, *, target_kind: str, tag: str, subfield: str, match_mode: str, find: str, ignore_case: bool, replacement_mode: str, replacement: str, occurrences: str) -> dict`.
- Result dictionary keys are exactly `matched_values`, `changed_values`, and `matched_occurrences`, each a nonnegative integer.

- [ ] **Step 1: Create the isolated worktree and mark TASK-180 In-Progress**

Use `superpowers:using-git-worktrees` from the approved main commit. Create a `task-180` branch and isolated worktree. In that worktree, update the ticket:

```markdown
Status: In-Progress

Plan:
- `docs/superpowers/plans/2026-07-30-task-180-core-structured-find-replace-authoring.md`
```

Run:

```bash
git branch --show-current
git status --short
```

Expected: the feature branch is isolated; only TASK-180's ticket is modified; none of the user's untracked main-worktree corpus or data paths appears in the feature diff.

- [ ] **Step 2: Pin existing replacement and Quick behavior before adding a kind**

Add characterization tests in `tests/test_task_builder.py`:

```python
def test_legacy_subfield_replace_compiler_contract_is_unchanged():
    rendered = task_builder.render_ops_to_python(
        [
            task_builder.Operation(
                kind="subfield-replace",
                params={
                    "tag": "035",
                    "code": "a",
                    "find": "TFeba",
                    "replace": "(SCTFEBA)",
                    "regex": True,
                    "ignore_case": False,
                },
            )
        ]
    )

    assert "_pat.sub('(SCTFEBA)', sf.value)" in rendered["body"]
    assert "if sf.code == 'a'" in rendered["body"]
    assert rendered["imports"] == ["import re", "from pymarc import Subfield"]


def test_existing_atomic_regex_replace_still_replaces_complete_subfield():
    rendered = task_builder.render_ops_to_python(
        [
            task_builder.Operation(
                kind="replace-field-subfield-and-indicators",
                params={
                    "tag": "035",
                    "match_ind1": " ",
                    "match_ind2": " ",
                    "match_code": "a",
                    "match_value": "TFeba",
                    "regex": True,
                    "new_ind1": " ",
                    "new_ind2": "9",
                    "new_code": "a",
                    "new_value": "(SCTFEBA)",
                },
            )
        ]
    )

    assert "replace_field_subfield_and_indicators(" in rendered["body"]
    assert "'(SCTFEBA)'" in rendered["body"]
```

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_builder.py \
  tests/test_batch_replace.py \
  tests/test_quick_replace_snapshot.py
```

Expected: PASS with all skips reported. Save this output as the pre-change characterization baseline.

- [ ] **Step 3: Write the failing engine validation and primary-regression tests**

Create `tests/test_guided_replace.py` with synthetic records:

```python
from pymarc import Field, Record, Subfield

from marcedit_web.lib import guided_replace


def _record():
    record = Record()
    record.add_field(Field(tag="001", data="TFeba123"))
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[
                Subfield(code="a", value="TFeba9780020306634"),
                Subfield(code="z", value="keep"),
            ],
        )
    )
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[Subfield(code="a", value="prefix-TFeba-suffix")],
        )
    )
    return record


def _params(**changes):
    params = {
        "target_kind": "subfield",
        "tag": "035",
        "subfield": "a",
        "match_mode": "contains",
        "find": "TFeba",
        "ignore_case": False,
        "replacement_mode": "matched_text",
        "replacement": "(SCTFEBA)",
        "occurrences": "all",
    }
    params.update(changes)
    return params


def _valid_params_for(target_kind, replacement_mode):
    params = _params(
        target_kind=target_kind,
        replacement_mode=replacement_mode,
    )
    if target_kind == "control_field":
        params.update(tag="001", subfield="")
    elif target_kind == "all_subfields":
        params.update(tag="035", subfield="")
    if replacement_mode in ("prepend", "append"):
        params.update(match_mode="none", find="", occurrences="all")
    elif replacement_mode == "whole_value":
        params.update(occurrences="first")
    return params


def test_matched_text_default_preserves_identifier_after_035_match():
    record = _record()

    result = guided_replace.apply_guided_find_replace(record, **_params())

    assert record["035"]["a"] == "(SCTFEBA)9780020306634"
    assert result == {
        "matched_values": 2,
        "changed_values": 2,
        "matched_occurrences": 2,
    }


def test_prepend_has_no_find_or_regex_and_runs_once_per_selected_value():
    record = _record()
    params = _params(
        match_mode="none",
        find="",
        replacement_mode="prepend",
        replacement="(OCoLC)",
    )

    result = guided_replace.apply_guided_find_replace(record, **params)

    assert record.get_fields("035")[0]["a"] == (
        "(OCoLC)TFeba9780020306634"
    )
    assert result["matched_values"] == 2
    assert result["matched_occurrences"] == 0


def test_empty_find_is_rejected_for_matched_text():
    errors = guided_replace.validate_request(**_params(find=""))
    assert errors == ("Find text is required for matched-text replacement.",)


def test_prepend_rejects_hidden_regex_state():
    errors = guided_replace.validate_request(
        **_params(
            match_mode="raw_regex",
            find="TFeba",
            replacement_mode="prepend",
        )
    )
    assert "prepend requires match mode 'none' and an empty Find value" in errors


def test_guided_replacement_backslashes_are_literal_not_capture_syntax():
    record = _record()
    guided_replace.apply_guided_find_replace(
        record, **_params(replacement=r"\1")
    )
    assert record["035"]["a"] == r"\19780020306634"
```

Run:

```bash
docker compose run --rm marcedit-web pytest -q tests/test_guided_replace.py
```

Expected: FAIL during import because `marcedit_web.lib.guided_replace` does not exist.

- [ ] **Step 4: Add table-driven RED coverage for the entire compatibility matrix**

Add parameterized tests. Each case must state the business reason in its test id:

```python
import pytest


@pytest.mark.parametrize(
    ("match_mode", "value", "find", "expected"),
    [
        ("contains", "xTFebay", "TFeba", "x(SCTFEBA)y"),
        ("starts_with", "TFebay", "TFeba", "(SCTFEBA)y"),
        ("starts_with", "xTFeba", "TFeba", "xTFeba"),
        ("ends_with", "xTFeba", "TFeba", "x(SCTFEBA)"),
        ("whole_value", "TFeba", "TFeba", "(SCTFEBA)"),
        ("whole_value", "TFeba123", "TFeba", "TFeba123"),
        ("raw_regex", "TFeba123", r"^(TFeba)(\d+)$", r"(SCTFEBA)\2"),
    ],
    ids=[
        "contains-preserves-both-sides",
        "starts-with-replaces-prefix",
        "starts-with-does-not-match-middle",
        "ends-with-replaces-suffix",
        "whole-value-replaces-equal-value",
        "whole-value-preserves-non-equal-value",
        "raw-regex-expands-capture",
    ],
)
def test_match_modes_replace_only_the_matched_text(
    match_mode, value, find, expected
):
    record = Record()
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[Subfield(code="a", value=value)],
        )
    )
    params = _params(match_mode=match_mode, find=find)
    guided_replace.apply_guided_find_replace(record, **params)
    assert record["035"]["a"] == expected


@pytest.mark.parametrize(
    "target_kind",
    ["control_field", "subfield", "all_subfields"],
)
@pytest.mark.parametrize(
    "replacement_mode",
    ["matched_text", "whole_value", "prepend", "append"],
)
def test_every_target_action_cell_is_supported(
    target_kind, replacement_mode
):
    params = _valid_params_for(target_kind, replacement_mode)
    assert guided_replace.validate_request(**params) == ()


def test_first_and_all_are_per_selected_value_not_per_record():
    record = Record()
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[
                Subfield(code="a", value="TFeba-TFeba"),
                Subfield(code="a", value="TFeba-TFeba"),
            ],
        )
    )
    params = _params(occurrences="first")
    guided_replace.apply_guided_find_replace(record, **params)
    assert record["035"].get_subfields("a") == [
        "(SCTFEBA)-TFeba",
        "(SCTFEBA)-TFeba",
    ]
```

Also cover ignored case, repeated fields, no match, unchanged replacement,
control tags 001/009, invalid 000/010 target boundaries, invalid subfield
codes, unknown modes, raw invalid captures, and input-record non-mutation on
validation failure.

Run the same focused command. Expected: still RED because no engine exists.

- [ ] **Step 5: Implement the minimum leaf engine**

Create `marcedit_web/lib/guided_replace.py` with no `marcedit_web` imports:

```python
"""Leaf deterministic engine for TASK-180 guided value replacement."""

from __future__ import annotations

import re
from typing import Callable, Iterator, Tuple

from pymarc import Field, Record, Subfield


TARGET_KINDS = ("control_field", "subfield", "all_subfields")
MATCH_MODES = (
    "contains",
    "starts_with",
    "ends_with",
    "whole_value",
    "raw_regex",
    "none",
)
REPLACEMENT_MODES = ("matched_text", "whole_value", "prepend", "append")
OCCURRENCE_MODES = ("first", "all")


def validate_request(
    *,
    target_kind: str,
    tag: str,
    subfield: str,
    match_mode: str,
    find: str,
    ignore_case: bool,
    replacement_mode: str,
    replacement: str,
    occurrences: str,
) -> Tuple[str, ...]:
    errors = []
    text_values = {
        "Target type": target_kind,
        "Tag": tag,
        "Subfield code": subfield,
        "Match mode": match_mode,
        "Find": find,
        "Replacement mode": replacement_mode,
        "Replacement": replacement,
        "Occurrence mode": occurrences,
    }
    for label, value in text_values.items():
        if not isinstance(value, str):
            errors.append(label + " must be text.")
    if not isinstance(ignore_case, bool):
        errors.append("Ignore-case setting must be true or false.")
    if errors:
        return tuple(errors)
    if target_kind not in TARGET_KINDS:
        errors.append("Target type is not supported.")
    if not re.fullmatch(r"\d{3}", tag or ""):
        errors.append("Tag must be exactly three numeric characters.")
    elif target_kind == "control_field" and tag not in {
        "001", "002", "003", "004", "005", "006", "007", "008", "009"
    }:
        errors.append("Control-field target must be 001 through 009.")
    elif target_kind != "control_field" and int(tag) < 10:
        errors.append("Subfield target must use tag 010 through 999.")
    if target_kind == "subfield" and not re.fullmatch(
        r"[a-z0-9]", subfield or ""
    ):
        errors.append("Subfield code must be one lowercase letter or digit.")
    if target_kind != "subfield" and subfield:
        errors.append("Subfield code must be empty for this target.")
    if match_mode not in MATCH_MODES:
        errors.append("Match mode is not supported.")
    if replacement_mode not in REPLACEMENT_MODES:
        errors.append("Replacement mode is not supported.")
    if occurrences not in OCCURRENCE_MODES:
        errors.append("Occurrence mode is not supported.")
    if replacement_mode in ("prepend", "append"):
        if match_mode != "none" or find:
            errors.append(
                replacement_mode
                + " requires match mode 'none' and an empty Find value."
            )
        if occurrences != "all":
            errors.append(
                replacement_mode + " requires occurrence mode 'all'."
            )
    elif not find:
        errors.append(
            "Find text is required for {0} replacement.".format(
                "matched-text"
                if replacement_mode == "matched_text"
                else "whole-selected-value"
            )
        )
    elif match_mode == "none":
        errors.append("Match mode 'none' is only valid for prepend or append.")
    if replacement_mode == "whole_value" and occurrences != "first":
        errors.append(
            "Whole-selected-value replacement requires occurrence mode "
            "'first'."
        )
    if (
        replacement_mode == "matched_text"
        and match_mode in ("starts_with", "ends_with", "whole_value")
        and occurrences != "first"
    ):
        errors.append(
            "This anchored match mode requires occurrence mode 'first'."
        )
    if match_mode == "raw_regex" and find:
        try:
            compiled = re.compile(find, re.IGNORECASE if ignore_case else 0)
            compiled.sub(replacement, "")
        except re.error as exc:
            errors.append("Regular expression is invalid: {0}".format(exc))
    return tuple(errors)
```

Implement private helpers that:

- yield `(field, subfield_index_or_none, value)` for each selected value;
- compile literal modes with `re.escape` and explicit anchors;
- use a replacement callback for non-raw modes so backslashes remain literal;
- use regex replacement-template expansion only for `match_mode="raw_regex"`;
- use `count=1` for `occurrences="first"` and `count=0` for `"all"`;
- use the first regex `Match.expand(replacement)` for whole-value replacement;
- reconstruct only changed `Subfield` instances;
- count matched values separately from changed values; and
- validate completely before mutating.

The public transform returns the exact JSON-safe dictionary from the interface.

- [ ] **Step 6: Run engine and legacy regression tests**

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_guided_replace.py \
  tests/test_task_builder.py \
  tests/test_batch_replace.py \
  tests/test_quick_replace_snapshot.py
```

Expected: PASS, no new skip, and Quick/legacy characterization output matches Step 2.

- [ ] **Step 7: Commit the engine**

```bash
git add \
  .tickets/TASK-180-structured-find-replace-authoring.md \
  marcedit_web/lib/guided_replace.py \
  tests/test_guided_replace.py \
  tests/test_task_builder.py
git commit -m "feat: add deterministic guided replace engine"
```

---

### Task 2: Compile the new kind without exposing it to AI

**Files:**
- Modify: `marcedit_web/lib/transforms.py`
- Modify: `marcedit_web/lib/task_builder.py`
- Modify: `marcedit_web/lib/ai_task_draft.py`
- Modify: `marcedit_web/lib/gemini_task_draft.py`
- Modify: `tests/test_task_builder.py`
- Modify: `tests/test_ai_task_draft.py`
- Modify: `tests/test_gemini_task_draft.py`
- Exercise: `tests/test_note_task_draft.py`
- Exercise: `tests/test_native_task_contract.py`

**Interfaces:**
- Consumes: `guided_replace.apply_guided_find_replace`.
- Produces: `transforms.apply_guided_find_replace`.
- Produces: palette kind `guided-find-replace` with only existing parameter types.
- Produces: generated local `_guided_replace_result`.
- Produces: `ai_task_draft.is_operation_kind_supported(kind: str) -> bool`.

- [ ] **Step 1: Write failing compiler and round-trip tests**

Add to `tests/test_task_builder.py`:

```python
def _guided_op():
    return task_builder.Operation(
        kind="guided-find-replace",
        params={
            "target_kind": "subfield",
            "tag": "035",
            "subfield": "a",
            "match_mode": "contains",
            "find": "TFeba",
            "ignore_case": False,
            "replacement_mode": "matched_text",
            "replacement": "(SCTFEBA)",
            "occurrences": "all",
            "condition": "always",
        },
    )


def test_guided_replace_compiles_to_one_shared_transform_call():
    rendered = task_builder.render_ops_to_python([_guided_op()])

    assert rendered["imports"] == [
        "from marcedit_web.lib.transforms import apply_guided_find_replace"
    ]
    assert "_guided_replace_result = apply_guided_find_replace(" in (
        rendered["body"]
    )
    assert "match_mode='contains'" in rendered["body"]
    assert "replacement_mode='matched_text'" in rendered["body"]
    assert "re.sub" not in rendered["body"]


def test_guided_replace_marker_round_trip_is_lossless():
    rendered = task_builder.render_ops_to_python([_guided_op()])
    parsed = task_builder.parse_ops_from_source(rendered["body"])
    assert parsed["form_editable"] is True
    assert parsed["ops"] == [_guided_op()]


def test_guided_replace_leader_condition_wraps_the_transform_call():
    op = _guided_op()
    op.params["condition"] = "books"
    rendered = task_builder.render_ops_to_python([op])
    lines = rendered["body"].splitlines()
    assert "if leader_type(record) in 'amt' and leader_biblevel(record) == 'm':" in lines
    call_index = next(
        i for i, line in enumerate(lines)
        if "_guided_replace_result = apply_guided_find_replace(" in line
    )
    assert lines[call_index].startswith("    ")
```

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_builder.py -k guided_replace
```

Expected: RED because the palette and compiler kind do not exist.

- [ ] **Step 2: Write failing AI-boundary tests**

Add to `tests/test_ai_task_draft.py`:

```python
def test_guided_replace_is_rejected_before_ai_param_validation():
    review = ai_task_draft.parse_ai_task_draft(
        json.dumps(
            {
                "task_name": "guided",
                "operations": [
                    {
                        "kind": "guided-find-replace",
                        "params": {"invented": {"unchecked": True}},
                    }
                ],
            }
        )
    )
    assert review.operations == ()
    assert len(review.rejected_operations) == 1
    assert review.rejected_operations[0].reason == (
        "guided-find-replace operations are not supported in AI drafts"
    )
```

Add to `tests/test_gemini_task_draft.py`:

```python
def test_gemini_prompt_does_not_advertise_guided_find_replace():
    prompt = gemini_task_draft.build_prompt("replace TFeba in 035 a")
    assert '"guided-find-replace"' not in prompt
    assert '"subfield-replace"' in prompt
```

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_ai_task_draft.py \
  tests/test_gemini_task_draft.py \
  tests/test_note_task_draft.py
```

Expected: RED because adding the palette kind without a shared exclusion would expose it.

- [ ] **Step 3: Re-export the leaf transform and add the palette/compiler branch**

At the bottom of `transforms.py`, after existing definitions, add:

```python
# TASK-180 leaf engine re-export. Keep this import at module scope only after
# guided_replace is verified not to import marcedit_web.lib.
from marcedit_web.lib.guided_replace import apply_guided_find_replace  # noqa: E402,F401
```

Add a `guided-find-replace` palette entry using `text`, `subfield_code`,
`select`, and `bool` only. Its defaults are:

```python
{
    "target_kind": "subfield",
    "tag": "",
    "subfield": "",
    "match_mode": "contains",
    "find": "",
    "ignore_case": False,
    "replacement_mode": "matched_text",
    "replacement": "",
    "occurrences": "all",
    "condition": "always",
}
```

Add `_render_one` code generation:

```python
if op.kind == "guided-find-replace":
    condition_key = str(p.get("condition", "always"))
    if condition_key not in LEADER_CONDITIONS:
        raise ValueError("record condition is not supported")
    call = (
        "_guided_replace_result = apply_guided_find_replace("
        "record, "
        "target_kind={0}, tag={1}, subfield={2}, match_mode={3}, "
        "find={4}, ignore_case={5}, replacement_mode={6}, "
        "replacement={7}, occurrences={8})"
    ).format(
        lit(str(p.get("target_kind", ""))),
        lit(str(p.get("tag", ""))),
        lit(str(p.get("subfield", ""))),
        lit(str(p.get("match_mode", ""))),
        lit(str(p.get("find", ""))),
        lit(bool(p.get("ignore_case", False))),
        lit(str(p.get("replacement_mode", ""))),
        lit(str(p.get("replacement", ""))),
        lit(str(p.get("occurrences", ""))),
    )
    condition_expr = LEADER_CONDITIONS[condition_key]
    imports = {"apply_guided_find_replace"}
    if condition_expr:
        imports |= {"leader_type", "leader_biblevel"}
        return ([f"if {condition_expr}:", f"    {call}"], imports, False)
    return ([call], imports, False)
```

- [ ] **Step 4: Implement one shared AI support decision**

In `ai_task_draft.py`:

```python
_UNSUPPORTED_AI_OPERATION_KINDS = {
    "custom",
    "guided-find-replace",
}


def is_operation_kind_supported(kind: str) -> bool:
    return kind not in _UNSUPPORTED_AI_OPERATION_KINDS
```

Use this function in `_validate_operation` before building `param_specs`.
In `gemini_task_draft.build_prompt`, replace the `kind != "custom"` filter:

```python
operations = [
    op
    for op in task_builder.OPERATIONS_PALETTE
    if ai_task_draft.is_operation_kind_supported(str(op.get("kind", "")))
]
```

Do not change note/Gemini examples, accepted legacy shapes, or
`_param_type_error`.

- [ ] **Step 5: Run compiler, AI, native-contract, and sandbox smoke tests**

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_builder.py \
  tests/test_guided_replace.py \
  tests/test_ai_task_draft.py \
  tests/test_gemini_task_draft.py \
  tests/test_note_task_draft.py \
  tests/test_native_task_contract.py
```

Expected: PASS with every skip reported.

Run the meaningful native freshness guard:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_native_task_contract.py::test_checked_in_contract_matches_every_golden_definition
git diff --exit-code main -- \
  marcedit_web/schemas/native-task-compiler-contract-v1.json
```

Expected: PASS and no manifest diff.

- [ ] **Step 6: Commit compiler and AI boundaries**

```bash
git add \
  marcedit_web/lib/transforms.py \
  marcedit_web/lib/task_builder.py \
  marcedit_web/lib/ai_task_draft.py \
  marcedit_web/lib/gemini_task_draft.py \
  tests/test_task_builder.py \
  tests/test_ai_task_draft.py \
  tests/test_gemini_task_draft.py
git commit -m "feat: compile guided replace operations"
```

---

### Task 3: Add guided validation, summaries, and progressive form controls

**Files:**
- Modify: `marcedit_web/lib/task_authoring.py`
- Modify: `marcedit_web/render/task_authoring.py`
- Modify: `marcedit_web/render/tasks.py`
- Modify: `tests/test_task_authoring.py`
- Modify: `tests/test_task_authoring_render.py`
- Modify: `tests/test_tasks_workspace_modes.py`
- Modify: `tests/test_tasks_export.py`

**Interfaces:**
- Consumes: `guided_replace.validate_request`.
- Produces: `normalize_guided_replace_operation(op: Mapping[str, Any]) -> dict`.
- Extends: `validate_operation` and `validate_operations`.
- Produces: `describe_guided_replace(op: Mapping[str, Any], previewed_discard_count: int = 0) -> str`.
- Produces: `render_guided_find_replace_params(params: dict, *, key_prefix: str) -> None`.
- Produces: `_default_params_for("guided-find-replace")` with the exact storage defaults.

- [ ] **Step 1: Write failing normalization, validation, and summary tests**

Add to `tests/test_task_authoring.py`:

```python
def _guided_operation(**changes):
    params = {
        "target_kind": "subfield",
        "tag": "035",
        "subfield": "a",
        "match_mode": "contains",
        "find": "TFeba",
        "ignore_case": False,
        "replacement_mode": "matched_text",
        "replacement": "(SCTFEBA)",
        "occurrences": "all",
        "condition": "always",
    }
    params.update(changes)
    return {"kind": "guided-find-replace", "params": params}


def test_guided_summary_promises_to_keep_both_sides_of_match():
    assert task_authoring.describe_guided_replace(
        _guided_operation()
    ) == (
        "In every 035 subfield a, replace every case-sensitive occurrence "
        "of “TFeba” with “(SCTFEBA)”. Keep text before and after each match."
    )


def test_whole_value_summary_names_destructive_preview_count():
    summary = task_authoring.describe_guided_replace(
        _guided_operation(replacement_mode="whole_value"),
        previewed_discard_count=4,
    )
    assert "discard the complete value" in summary
    assert "4 previewed values" in summary


def test_prepend_with_hidden_matching_state_is_preserved_and_rejected():
    normalized = task_authoring.normalize_guided_replace_operation(
        _guided_operation(
            replacement_mode="prepend",
            match_mode="contains",
            find="stale",
        )
    )
    assert normalized["params"]["match_mode"] == "contains"
    assert normalized["params"]["find"] == "stale"
    assert task_authoring.validate_operation(normalized) == (
        "prepend requires match mode 'none' and an empty Find value.",
    )


def test_unknown_guided_parameter_blocks_lossy_round_trip():
    operation = _guided_operation()
    operation["params"]["future_option"] = True
    assert task_authoring.validate_operation(operation) == (
        "operation parameters contain unexpected keys: future_option",
    )


def test_guided_operation_editor_normalization_is_lossless():
    operation = _guided_operation(
        match_mode="raw_regex",
        find=r"^(TFeba)(\d+)$",
        replacement=r"(SCTFEBA)\2",
    )
    assert task_authoring.normalize_operations_for_editor(
        [operation]
    ) == [operation]
```

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_authoring.py -k guided
```

Expected: RED because guided helpers do not exist.

- [ ] **Step 2: Write failing progressive-renderer tests**

Extend `FakeStreamlit` only with the controls used by the new renderer,
including `checkbox`, `radio`, `metric`, and `spinner`. Add:

```python
def test_guided_default_shows_plain_find_without_regex(monkeypatch):
    fake = FakeStreamlit()
    renderer = _renderer(monkeypatch, fake)
    params = _guided_operation()["params"]

    renderer.render_guided_find_replace_params(params, key_prefix="op_0")

    assert "Where should Smith Metadata Studio look?" in fake.selectbox_labels
    assert "Find" in fake.text_input_labels
    assert "Write a regular expression directly" in fake.checkbox_labels
    assert params["match_mode"] == "contains"


def test_prepend_hides_find_and_occurrence_controls(monkeypatch):
    fake = FakeStreamlit(
        selectbox_values={"What should it change?": "prepend"}
    )
    renderer = _renderer(monkeypatch, fake)
    params = _guided_operation()["params"]

    renderer.render_guided_find_replace_params(params, key_prefix="op_0")

    assert "Find" not in fake.text_input_labels
    assert params["match_mode"] == "none"
    assert params["find"] == ""


def test_raw_regex_is_explicit_and_preserves_entered_strings(monkeypatch):
    fake = FakeStreamlit(
        checked={"op_0_advanced_regex"},
        text_values={
            "Find regular expression": r"^(TFeba)(\d+)$",
            "Replace with": r"(SCTFEBA)\2",
        },
    )
    renderer = _renderer(monkeypatch, fake)
    params = _guided_operation()["params"]

    renderer.render_guided_find_replace_params(params, key_prefix="op_0")

    assert params["match_mode"] == "raw_regex"
    assert params["find"] == r"^(TFeba)(\d+)$"
    assert params["replacement"] == r"(SCTFEBA)\2"


def test_leaving_raw_mode_requires_confirmation_before_discard(monkeypatch):
    params = _guided_operation(
        match_mode="raw_regex",
        find=r"^(TFeba)(\d+)$",
        replacement=r"(SCTFEBA)\2",
    )["params"]
    first = FakeStreamlit()
    renderer = _renderer(monkeypatch, first)
    renderer.render_guided_find_replace_params(params, key_prefix="op_0")
    assert params["match_mode"] == "raw_regex"
    assert params["find"] == r"^(TFeba)(\d+)$"
    assert any("discard" in text.lower() for text in first.warnings)

    confirmed = FakeStreamlit(pressed={"op_0_mode_switch_discard"})
    renderer = _renderer(monkeypatch, confirmed)
    renderer.render_guided_find_replace_params(
        params, key_prefix="op_0"
    )
    assert params["match_mode"] == "contains"
    assert params["find"] == ""
```

The fake must record full widget keys and assert distinct `op_0_*` keys so
multiple operation cards cannot collide.

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_authoring_render.py -k guided
```

Expected: RED because the renderer does not exist.

- [ ] **Step 3: Implement guided normalization, validation, and summaries**

In `task_authoring.py`, define the exact allowed parameter set:

```python
_GUIDED_REPLACE_PARAMS = {
    "target_kind",
    "tag",
    "subfield",
    "match_mode",
    "find",
    "ignore_case",
    "replacement_mode",
    "replacement",
    "occurrences",
    "condition",
}
```

`normalize_guided_replace_operation` must:

- deep-copy the operation;
- set only documented defaults for missing keys;
- preserve target/subfield combinations exactly so incompatible hidden values
  remain visible to validation;
- preserve inconsistent hidden Find/match values so validation fails loud
  instead of deleting cataloger input;
- retain raw regex strings byte-for-byte; and
- retain unknown keys so `validate_operation` can reject them instead of
  silently deleting them.

Make `normalize_operation` delegate `guided-find-replace` to this helper, so
the existing `normalize_operations_for_editor` open path handles saved guided
operations without another writer or database migration.

Extend `validate_operation` with:

```python
if kind == "guided-find-replace":
    normalized = normalize_guided_replace_operation(op)
    params = normalized["params"]
    errors = list(
        guided_replace.validate_request(
            target_kind=params["target_kind"],
            tag=params["tag"],
            subfield=params["subfield"],
            match_mode=params["match_mode"],
            find=params["find"],
            ignore_case=params["ignore_case"],
            replacement_mode=params["replacement_mode"],
            replacement=params["replacement"],
            occurrences=params["occurrences"],
        )
    )
    if params["condition"] not in task_builder.LEADER_CONDITIONS:
        errors.append("record condition is not supported")
    unexpected = sorted(set(params) - _GUIDED_REPLACE_PARAMS)
    if unexpected:
        errors.append(
            "operation parameters contain unexpected keys: {0}".format(
                ", ".join(unexpected)
            )
        )
    return tuple(errors)
```

Implement summaries directly from normalized choices; never infer from
generated Python.

- [ ] **Step 4: Implement the progressive card and editor delegation**

In `render/task_authoring.py`, add labeled option tuples and
`render_guided_find_replace_params`. Use `_key(key_prefix, ...)` for every
widget. Preserve Find/raw values in `st.session_state` while a switch to
prepend, append, or guided non-regex mode awaits confirmation. On the first
switch attempt, keep `params` unchanged and show **Keep current mode** and
**Discard matching text and switch**. Only the second button sets
`match_mode="none"` and `find=""` for prepend/append, or clears the raw
expression for guided mode. Do not discard values on the rerun that asks for
confirmation. Use keys `op_N_mode_switch_keep` and
`op_N_mode_switch_discard`.

The renderer shows First/Every only for contains or raw-regex matched-text
replacement. It stores `occurrences="first"` for starts-with, ends-with,
whole-value match, and whole-selected-value replacement. It stores
`occurrences="all"` for prepend/append. These canonical hidden values must
match `guided_replace.validate_request`.

In `render/tasks.py`, add the following condition as an `elif` in the existing
operation-kind chain:

```python
if op["kind"] == "guided-find-replace":
    task_authoring_render.render_guided_find_replace_params(
        params, key_prefix=f"op_{i}"
    )
```

Render `describe_guided_replace` below the controls. Do not use the generic
palette parameter loop for this kind.

Add exact defaults in `_default_params_for` and verify form save invokes
`validate_operations` but does not inspect preview state.

- [ ] **Step 5: Run authoring, save, legacy, and AI regressions**

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_authoring.py \
  tests/test_task_authoring_render.py \
  tests/test_tasks_workspace_modes.py \
  tests/test_task_builder.py \
  tests/test_ai_task_draft.py \
  tests/test_gemini_task_draft.py \
  tests/test_note_task_draft.py
```

Expected: PASS with every skip reported. Explicitly confirm a syntactically
valid raw-regex task saves when `session.current_store()` returns `None`.

- [ ] **Step 6: Commit the guided card**

```bash
git add \
  marcedit_web/lib/task_authoring.py \
  marcedit_web/render/task_authoring.py \
  marcedit_web/render/tasks.py \
  tests/test_task_authoring.py \
  tests/test_task_authoring_render.py \
  tests/test_tasks_workspace_modes.py
git commit -m "feat: add guided find replace task controls"
```

---

### Task 4: Add sandboxed preview and submission-only preview currency

**Files:**
- Modify: `marcedit_web/lib/sandbox.py`
- Create: `marcedit_web/lib/guided_replace_preview.py`
- Modify: `marcedit_web/render/task_authoring.py`
- Modify: `marcedit_web/render/tasks.py`
- Modify: `tests/test_sandbox.py`
- Create: `tests/test_guided_replace_preview.py`
- Modify: `tests/test_task_authoring_render.py`
- Modify: `tests/test_tasks_workspace_modes.py`

**Interfaces:**
- Extends: `sandbox.TaskSpec` with `capture_result: Optional[str] = None`.
- Extends: `sandbox.SandboxResult` with `captured_results: list[dict]`.
- Produces: `GuidedReplacePreview` with `request`, `store_id`, `store_revision`, `before`, `after`, `result`, and `error`.
- Produces: `build_preview(store, operation: Mapping[str, Any]) -> GuidedReplacePreview`.
- Produces: `is_current(preview, store, operation: Mapping[str, Any]) -> bool`.
- Produces: `preview_cache_key(operation: Mapping[str, Any]) -> str`, the canonical normalized request JSON, not a compiler fingerprint.

- [ ] **Step 1: Write failing optional sandbox-capture tests**

Add to `tests/test_sandbox.py`:

```python
def test_trusted_task_result_can_be_captured_for_preview(one_record_bytes):
    spec = sandbox.TaskSpec(
        name="capture",
        body="_guided_replace_result = {'matched_values': 2, "
             "'changed_values': 1, 'matched_occurrences': 2}",
        capture_result="_guided_replace_result",
    )
    result = sandbox.run_tasks_subprocess(
        [spec], record_bytes=one_record_bytes
    )
    assert result.returncode == 0
    assert result.captured_results == [
        {
            "record_index": 1,
            "task": "capture",
            "result": {
                "matched_values": 2,
                "changed_values": 1,
                "matched_occurrences": 2,
            },
        }
    ]


def test_default_sandbox_call_does_not_capture_task_namespace(
    one_record_bytes,
):
    result = sandbox.run_tasks_subprocess(
        [sandbox.TaskSpec(name="plain", body="pass")],
        record_bytes=one_record_bytes,
    )
    assert result.captured_results == []
```

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_sandbox.py -k captured
```

Expected: RED because capture fields do not exist.

- [ ] **Step 2: Implement bounded JSON-safe capture**

Extend the existing dataclasses without breaking their constructors:

```python
@dataclass
class TaskSpec:
    name: str
    body: str
    imports: list[str] = field(default_factory=list)
    capture_result: Optional[str] = None


@dataclass
class SandboxResult:
    output_path: Path
    errors: list[dict]
    error_count: int = 0
    stderr: str = ""
    returncode: int = 0
    timed_out: bool = False
    cancelled: bool = False
    captured_results: list[dict] = field(default_factory=list)
```

Serialize `capture_result` in `tasks_list`. In the child, after successful
`exec`, append only requested results:

```python
capture_name = task.get("capture_result")
if capture_name:
    value = ns.get(capture_name)
    json.dumps(value)
    captured_results.append({
        "record_index": idx,
        "task": _bounded_text(
            task.get("name", "?"),
            args.max_task_chars,
            args.max_task_bytes,
        ),
        "result": value,
    })
```

Initialize `captured_results = []` and include it in `errors.json`. The parent
uses `payload.get("captured_results", [])`, so old/malformed error fixtures
remain compatible. Capture is available only when trusted parent code sets
`TaskSpec.capture_result`; normal task execution passes `None`.

Reject a non-JSON-safe captured value as a normal `transform-failed` error.
Cap capture to the existing input record count and use only bounded integers
and strings from the guided engine; do not expose arbitrary namespace values.

- [ ] **Step 3: Write failing preview equivalence and staleness tests**

Create `tests/test_guided_replace_preview.py`:

```python
import copy
import io

import pymarc
from pymarc import Field, Record, Subfield

from marcedit_web.lib import guided_replace_preview, sandbox
from marcedit_web.lib.record_store import RecordStore


def _record_with_035(value):
    record = Record()
    record.add_field(
        Field(
            tag="035",
            indicators=[" ", " "],
            subfields=[Subfield(code="a", value=value)],
        )
    )
    return record


def _record_bytes(record):
    stream = io.BytesIO()
    writer = pymarc.MARCWriter(stream)
    writer.write(record)
    return stream.getvalue()


def _store_with_035(tmp_path, value):
    return RecordStore.from_bytes(
        _record_bytes(_record_with_035(value)),
        tmp_dir=tmp_path / "store",
    )


def _guided_operation(**changes):
    params = {
        "target_kind": "subfield",
        "tag": "035",
        "subfield": "a",
        "match_mode": "contains",
        "find": "TFeba",
        "ignore_case": False,
        "replacement_mode": "matched_text",
        "replacement": "(SCTFEBA)",
        "occurrences": "all",
        "condition": "always",
    }
    params.update(changes)
    return {"kind": "guided-find-replace", "params": params}


def _timed_out_result(tmp_path):
    return sandbox.SandboxResult(
        output_path=tmp_path / "timed-out.mrc",
        errors=[],
        returncode=-9,
        timed_out=True,
    )


def test_preview_runs_compiled_operation_in_sandbox_without_mutating_store(
    tmp_path,
):
    store = _store_with_035(tmp_path, "TFeba9780020306634")
    operation = _guided_operation()
    before = store.get(0)["035"]["a"]

    preview = guided_replace_preview.build_preview(store, operation)

    assert preview.error is None
    assert preview.before == "035 $aTFeba9780020306634"
    assert preview.after == "035 $a(SCTFEBA)9780020306634"
    assert preview.result == {
        "matched_values": 1,
        "changed_values": 1,
        "matched_occurrences": 1,
    }
    assert store.get(0)["035"]["a"] == before


def test_preview_currency_requires_same_store_revision_and_request(tmp_path):
    store = _store_with_035(tmp_path, "TFeba123")
    operation = _guided_operation()
    preview = guided_replace_preview.build_preview(store, operation)
    assert guided_replace_preview.is_current(preview, store, operation)

    changed = copy.deepcopy(operation)
    changed["params"]["replacement"] = "(OTHER)"
    assert not guided_replace_preview.is_current(preview, store, changed)

    store.replace(0, _record_with_035("TFeba456"))
    assert not guided_replace_preview.is_current(preview, store, operation)


def test_raw_regex_timeout_is_an_error_not_a_current_preview(
    tmp_path, monkeypatch
):
    store = _store_with_035(tmp_path, "TFeba123")
    monkeypatch.setattr(
        guided_replace_preview.sandbox,
        "run_tasks_subprocess",
        lambda *args, **kwargs: _timed_out_result(tmp_path),
    )
    preview = guided_replace_preview.build_preview(
        store, _guided_operation(match_mode="raw_regex")
    )
    assert "timed out" in preview.error
    assert not guided_replace_preview.is_current(
        preview, store, _guided_operation(match_mode="raw_regex")
    )
```

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_guided_replace_preview.py
```

Expected: RED because the preview module does not exist.

- [ ] **Step 4: Implement one-record sandbox preview**

`build_preview` must:

1. normalize and validate the operation;
2. return a clear no-file error if the store has no records;
3. serialize only `store.get(0)` to MARC bytes;
4. compile only that operation through `task_builder.render_ops_to_python`;
5. execute a `TaskSpec` with
   `capture_result="_guided_replace_result"`;
6. parse exactly one output record and one captured result;
7. format only the selected target values for before/after display;
8. delete its temporary directory in `finally`; and
9. retain only normalized request data, store identity/revision, display
   strings, counts, and bounded error text.

Use:

```python
@dataclass(frozen=True)
class GuidedReplacePreview:
    request: dict
    store_id: Optional[int]
    store_revision: Optional[int]
    before: str = ""
    after: str = ""
    result: Optional[dict] = None
    error: Optional[str] = None
```

`preview_cache_key` returns
`json.dumps(normalized["params"], sort_keys=True, separators=(",", ":"))`.
`is_current` also requires `preview.error is None`, identical store id,
identical store revision, and equal normalized request dictionaries.

- [ ] **Step 5: Add preview controls and cache without making save depend on them**

Use one session dictionary:

```python
K_GUIDED_REPLACE_PREVIEWS = "task_guided_replace_previews"
```

The dictionary key is `preview_cache_key(operation)`. A successful or failed
preview replaces only that request's prior entry. Changing an operation
produces a different key and therefore cannot reuse an old preview.

The card shows:

- **Preview this operation**;
- matched values, changed values, and occurrences;
- before and after blocks;
- the destructive whole-value count in its summary, using
  `preview.result["matched_values"]`; and
- explicit timeout, validation, no-file, and zero-match messages.

Do not run the sandbox on every Streamlit rerun. Only the button runs preview.
Do not clear the cache when saving; raw-regex submission immediately after
save must still find the current request/store preview.

- [ ] **Step 6: Add submission-only raw preview tests and gate**

In `tests/test_tasks_workspace_modes.py`, use its existing
`_FakeStreamlit`, `_tasks_render`, `_form_save_state`, and
`_wire_successful_save` helpers:

```python
def test_valid_raw_regex_saves_without_file_or_preview(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    operation = {
        "kind": "guided-find-replace",
        "params": {
            "target_kind": "subfield",
            "tag": "035",
            "subfield": "a",
            "match_mode": "raw_regex",
            "find": r"^(TFeba)(\d+)$",
            "ignore_case": False,
            "replacement_mode": "matched_text",
            "replacement": r"(SCTFEBA)\2",
            "occurrences": "all",
            "condition": "always",
        },
    }
    fake_st.session_state.update(
        _form_save_state(tasks_render, [operation])
    )
    saved = []
    _wire_successful_save(monkeypatch, tasks_render, saved)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: None)

    tasks_render._save_callback(tmp_path)

    assert tasks_render.K_SAVE_ERROR not in fake_st.session_state
    assert len(saved) == 1
```

In `tests/test_tasks_export.py`, use its existing `_FakeStreamlit` and
`_tasks_render` submission harness:

```python
def test_raw_regex_submission_requires_current_preview(
    monkeypatch, tmp_path
):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render()
    monkeypatch.setattr(tasks_render, "st", fake_st)
    operation = tasks_render.Operation(
        kind="guided-find-replace",
        params={
            "target_kind": "subfield",
            "tag": "035",
            "subfield": "a",
            "match_mode": "raw_regex",
            "find": r"^(TFeba)(\d+)$",
            "ignore_case": False,
            "replacement_mode": "matched_text",
            "replacement": r"(SCTFEBA)\2",
            "occurrences": "all",
            "condition": "always",
        },
    )
    body = tasks_render.task_builder.render_ops_to_python([operation])["body"]
    monkeypatch.setattr(
        tasks_render.editor,
        "parse_user_task_file",
        lambda _path: {"body": body},
    )
    store = SimpleNamespace(revision=0)
    monkeypatch.setattr(tasks_render.session, "current_store", lambda: store)
    fake_st.session_state[
        tasks_render.K_GUIDED_REPLACE_PREVIEWS
    ] = {}
    submitted = []
    monkeypatch.setattr(
        tasks_render.operation_submission,
        "submit_quick_load_task_run",
        lambda **kwargs: submitted.append(kwargs),
    )

    tasks_render._submit_queued_run(["raw-guided"], tmp_path)

    assert submitted == []
    assert "Preview this raw regular expression" in fake_st.errors[-1]
```

At submission, parse operations once. For each `guided-find-replace` with
`match_mode=="raw_regex"`, require a cache entry for its canonical request and
`guided_replace_preview.is_current(preview, store, op.to_dict())`.
Literal guided operations do not require preview.

- [ ] **Step 7: Run sandbox, preview, save, and submission regressions**

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_sandbox.py \
  tests/test_guided_replace_preview.py \
  tests/test_task_authoring_render.py \
  tests/test_tasks_workspace_modes.py \
  tests/test_tasks_export.py \
  tests/test_guided_replace.py \
  tests/test_task_builder.py
```

Expected: PASS with every skip reported. Verify launcher errors, timeouts, and
ordinary durable task runs still return `captured_results == []`.

- [ ] **Step 8: Commit sandboxed preview**

```bash
git add \
  marcedit_web/lib/sandbox.py \
  marcedit_web/lib/guided_replace_preview.py \
  marcedit_web/render/task_authoring.py \
  marcedit_web/render/tasks.py \
  tests/test_sandbox.py \
  tests/test_guided_replace_preview.py \
  tests/test_task_authoring_render.py \
  tests/test_tasks_workspace_modes.py \
  tests/test_tasks_export.py
git commit -m "feat: preview guided replacements in sandbox"
```

---

### Task 5: Block empty-find imports and compose submission preflight

**Files:**
- Modify: `marcedit_web/lib/marcedit_import.py`
- Modify: `marcedit_web/lib/task_authoring.py`
- Modify: `marcedit_web/render/tasks.py`
- Modify: `tests/test_marcedit_import.py`
- Modify: `tests/test_task_authoring.py`
- Modify: `tests/test_tasks_workspace_modes.py`
- Modify: `tests/test_tasks_export.py`

**Interfaces:**
- Produces: `submission_preflight_issues(body: str) -> tuple[str, ...]`.
- Replaces direct `_submit_queued_run` use of `unresolved_add_build_instructions`.
- Preserves: `unresolved_add_build_instructions(body: str)`.

- [ ] **Step 1: Write failing empty-find importer tests**

Add to `tests/test_marcedit_import.py`:

```python
def test_empty_find_subfield_edit_is_unresolved_not_python_replace():
    source = (
        "#DESCRIPTION#Synthetic empty-find safety\n"
        "SUBFIELD_EDIT\t856\ty\t\tSmith: Link to resource\t101|0\n"
    )
    result = marcedit_import.convert_tasksfile_text(
        source,
        name="empty-find",
        description_fallback="",
    )

    assert result.unsupported == (
        "SUBFIELD_EDIT\t856\ty\t\tSmith: Link to resource\t101|0",
    )
    assert "sf.value.replace(''," not in result.body
    assert "# OP: custom" in result.body
    assert "empty Find has no proven external meaning" in result.body


def test_unproven_caret_b_subfield_edit_remains_unresolved():
    source = (
        "SUBFIELD_EDIT\t856\tu\t^b\t"
        "http://libproxy.smith.edu/login?url=\t0|0\n"
    )
    result = marcedit_import.convert_tasksfile_text(
        source,
        name="caret-b",
        description_fallback="",
    )
    assert result.unsupported == (
        "SUBFIELD_EDIT\t856\tu\t^b\t"
        "http://libproxy.smith.edu/login?url=\t0|0",
    )
    assert "unproven external syntax '^b'" in result.body
    assert "sf.value.replace('^b'," not in result.body


def test_nonempty_subfield_edit_keeps_legacy_import_contract():
    source = (
        "SUBFIELD_EDIT\t035\ta\tTFeba\t(SCTFEBA)\t0|0\n"
    )
    result = marcedit_import.convert_tasksfile_text(
        source,
        name="nonempty",
        description_fallback="",
    )
    assert result.unsupported == ()
    assert (
        '# OP: subfield-replace {"code": "a", "find": "TFeba", '
        '"replace": "(SCTFEBA)", "tag": "035"}'
    ) in result.body
    assert "sf.value.replace('TFeba', '(SCTFEBA)')" in result.body
```

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_marcedit_import.py -k subfield_edit
```

Expected: first test RED because empty Find currently emits executable
`str.replace`.

- [ ] **Step 2: Write failing composed-preflight tests**

Add to `tests/test_task_authoring.py`:

```python
def test_submission_preflight_composes_add_build_and_empty_find_issues():
    body = "\n".join(
        [
            "# OP: custom {\"code\": \"# TODO: buildnewfield template 'x'\"}",
            "# TODO: buildnewfield template 'x' — recreate",
            (
                "# OP: subfield-replace "
                "{\"code\": \"y\", \"find\": \"\", "
                "\"replace\": \"Smith\", \"tag\": \"856\"}"
            ),
            "pass",
        ]
    )
    issues = task_authoring.submission_preflight_issues(body)
    assert len(issues) == 2
    assert "buildnewfield" in issues[0]
    assert "empty Find" in issues[1]


def test_preflight_does_not_pattern_match_arbitrary_python_source():
    body = "text = \"sf.value.replace('', 'X')\"\npass"
    assert task_authoring.submission_preflight_issues(body) == ()
```

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_task_authoring.py -k preflight
```

Expected: RED because the composed helper does not exist.

- [ ] **Step 3: Make empty-find import fail closed**

At the start of `_emit_subfield_edit`, after extracting values:

```python
if find == "":
    return HandlerEmission(
        code=(
            "# TODO: SUBFIELD_EDIT has an empty Find value; "
            "empty Find has no proven external meaning — recreate it "
            "with an explicit guided action"
        ),
    )
if find == "^b":
    return HandlerEmission(
        code=(
            "# TODO: SUBFIELD_EDIT uses unproven external syntax '^b'; "
            "recreate it with an explicit guided action"
        ),
    )
```

For either refusal, the top-level converter emits a `custom` marker, adds the
source line to `unsupported`, and `_save_exact_conversion` refuses
persistence. Do not interpret `^b` as prepend or regex in this task.

- [ ] **Step 4: Implement one composed marker-aware preflight**

In `task_authoring.py`:

```python
def submission_preflight_issues(body: str) -> tuple[str, ...]:
    issues = list(unresolved_add_build_instructions(body))
    parsed = task_builder.parse_ops_from_source(body)
    if parsed["form_editable"]:
        for index, op in enumerate(parsed["ops"], start=1):
            if (
                op.kind == "subfield-replace"
                and str(op.params.get("find", "")) == ""
            ):
                issues.append(
                    "Operation {0} is a saved Subfield Replace with an empty "
                    "Find value. Recreate it with an explicit guided action "
                    "before running this task.".format(index)
                )
    return tuple(issues)
```

Replace `_submit_queued_run`'s direct unresolved-Add/Build call with this one
helper. Keep raw-regex preview currency as the subsequent stateful check;
marker/source safety remains one composed pure preflight.

Add to `tests/test_tasks_export.py`:

```python
def test_saved_empty_find_marker_is_not_submitted(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render()
    monkeypatch.setattr(tasks_render, "st", fake_st)
    body = (
        '# OP: subfield-replace {"code": "y", "find": "", '
        '"replace": "Smith: Link to resource", "tag": "856"}\n'
        "pass"
    )
    monkeypatch.setattr(
        tasks_render.editor,
        "parse_user_task_file",
        lambda _path: {"body": body},
    )
    submitted = []
    monkeypatch.setattr(
        tasks_render.operation_submission,
        "submit_quick_load_task_run",
        lambda **kwargs: submitted.append(kwargs),
    )

    tasks_render._submit_queued_run(["empty-find"], tmp_path)

    assert submitted == []
    assert "empty Find value" in fake_st.errors[-1]
```

- [ ] **Step 5: Verify importer refusal reaches the save boundary**

Add to `tests/test_tasks_workspace_modes.py` using the same import harness as
`test_new_unresolved_text_import_is_not_persisted`:

```python
def test_empty_find_import_is_not_persisted(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit()
    tasks_render = _tasks_render(monkeypatch, fake_st)
    monkeypatch.setattr(
        tasks_render.session, "current_user_id", lambda: "cat@smith.edu"
    )
    monkeypatch.setattr(
        tasks_render.quotas, "check_upload", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        tasks_render, "audit_event", lambda *args, **kwargs: None
    )
    saved = []
    monkeypatch.setattr(
        tasks_render.task_db,
        "save_task",
        lambda **kwargs: saved.append(kwargs),
    )
    upload = SimpleNamespace(
        name="empty-find.tasksfile",
        getvalue=lambda: (
            b"SUBFIELD_EDIT\t856\ty\t\t"
            b"Smith: Link to resource\t101|0\n"
        ),
    )

    tasks_render._do_marcedit_import(upload, tmp_path)

    assert saved == []
    assert any("Not imported" in text for text in fake_st.warnings)
    assert fake_st.code_blocks == [
        "SUBFIELD_EDIT\t856\ty\t\tSmith: Link to resource\t101|0"
    ]
```

- [ ] **Step 6: Run import, preflight, traversal, and run-flow regressions**

Run:

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_marcedit_import.py \
  tests/test_task_authoring.py \
  tests/test_tasks_workspace_modes.py \
  tests/test_tasks_export.py \
  tests/test_task_import_traversal.py \
  tests/test_codegen_safety.py
```

Expected: PASS with every skip reported. Confirm nonempty `SUBFIELD_EDIT`,
unresolved Add/Build, arbitrary code-mode tasks, and archive safety retain
their established behavior.

- [ ] **Step 7: Commit empty-find safety**

```bash
git add \
  marcedit_web/lib/marcedit_import.py \
  marcedit_web/lib/task_authoring.py \
  marcedit_web/render/tasks.py \
  tests/test_marcedit_import.py \
  tests/test_task_authoring.py \
  tests/test_tasks_workspace_modes.py \
  tests/test_tasks_export.py
git commit -m "fix: block ambiguous empty find imports"
```

---

### Task 6: Document, verify, browser-test, and complete TASK-180

**Files:**
- Modify: `docs/task-authoring-syntax.md`
- Create: `docs/superpowers/evidence/task-180-guided-find-replace-browser-smoke.md`
- Modify: `.tickets/TASK-180-structured-find-replace-authoring.md`
- Modify: `.tickets/TASK-174-smith-metadata-studio-open-task-migration.md`

**Interfaces:**
- Consumes all TASK-180 implementation and test interfaces.
- Produces reproducible automated, browser, review, and commit evidence.

- [ ] **Step 1: Add the core Find and Replace syntax reference**

Document:

```markdown
## Guided Find and Replace

The default changes only matched text. For example, finding `TFeba` in
035 subfield `a` and replacing it with `(SCTFEBA)` changes:

`TFeba9780020306634` → `(SCTFEBA)9780020306634`

Text before and after the match remains unless **Replace the whole selected
value** is chosen explicitly.

Targets in this release are control fields 001–009, one subfield code in one
tag, and all subfield values in one tag. Prepend and append act once per
selected value and do not use an empty Find.

Raw regular expressions are available under the advanced control. They are
stored exactly with match mode `raw_regex`, validated before save, and must
receive a current sandbox preview before the task can be submitted.
```

Include the complete two-table compatibility matrix and explain first/all
occurrences per selected value. Link TASK-184/TASK-185 behavior as deferred;
do not document it as currently available.

- [ ] **Step 2: Run the focused supported Docker suite**

Run:

```bash
docker compose run --rm marcedit-web pytest -ra \
  tests/test_guided_replace.py \
  tests/test_guided_replace_preview.py \
  tests/test_task_builder.py \
  tests/test_task_authoring.py \
  tests/test_task_authoring_render.py \
  tests/test_tasks_workspace_modes.py \
  tests/test_sandbox.py \
  tests/test_marcedit_import.py \
  tests/test_task_import_traversal.py \
  tests/test_codegen_safety.py \
  tests/test_batch_replace.py \
  tests/test_quick_replace_snapshot.py \
  tests/test_ai_task_draft.py \
  tests/test_note_task_draft.py \
  tests/test_gemini_task_draft.py \
  tests/test_native_task_contract.py
```

Expected: all tests pass. Record the exact pass count, skip count, skip
reasons, duration, and image identifier. Any failure or unreported skip keeps
TASK-180 In-Progress.

- [ ] **Step 3: Run the native contract guards**

```bash
docker compose run --rm marcedit-web pytest -q \
  tests/test_native_task_contract.py::test_checked_in_contract_matches_every_golden_definition
git diff --exit-code main -- \
  marcedit_web/schemas/native-task-compiler-contract-v1.json
```

Expected: PASS and no schema-manifest diff.

- [ ] **Step 4: Build and run the complete Docker suite**

```bash
docker compose build marcedit-web
docker compose run --rm marcedit-web pytest -ra
```

Expected: zero failures. Record every skip; do not summarize skipped tests as
passing.

- [ ] **Step 5: Start the isolated local application**

```bash
docker compose up -d marcedit-web
docker compose ps
```

Expected: the service is healthy on `http://localhost:8501`. Use the existing
local OAuth/test-database procedure recorded for TASK-179. Do not copy
production credentials or modify the production database.

- [ ] **Step 6: Perform cataloger browser acceptance with synthetic MARC**

Use the browser-control skill because this step requires interacting with the
local Streamlit UI. Verify:

1. Build a guided 035$a operation: Contains `TFeba`, replace matched text with
   `(SCTFEBA)`, case-sensitive, every occurrence.
2. Preview `TFeba9780020306634` and observe
   `(SCTFEBA)9780020306634`.
3. Switch deliberately to whole-selected-value and verify the summary names
   the number of previewed values that will be discarded.
4. Build prepend and append operations; verify Find and regex controls are
   absent and each action occurs once per selected value.
5. Target one control field and then all subfields in a data-field tag.
6. Enter raw regex `^(TFeba)(\d+)$` with replacement `(SCTFEBA)\2`; verify it
   saves, cannot submit before preview, previews successfully, and then
   submits.
7. Change the raw replacement after preview and verify submission is blocked
   until re-previewed.
8. Save and reopen; verify target, match mode, raw strings, replacement scope,
   occurrences, case setting, and condition are unchanged.
9. Import a synthetic empty-find `SUBFIELD_EDIT`; verify it is visible as
   unresolved and is not saved as executable.
10. Confirm the legacy Subfield Replace, Quick Find/Replace, and AI drafting
    surfaces have not gained new behavior.

- [ ] **Step 7: Record browser evidence**

Create
`docs/superpowers/evidence/task-180-guided-find-replace-browser-smoke.md`
with:

- candidate commit;
- Docker image identifier;
- browser URL and non-production authentication method;
- synthetic input and exact 035 before/after;
- matched/changed/occurrence metrics;
- raw regex save/submission/staleness observations;
- save/reopen result;
- empty-find refusal;
- legacy/Quick/AI characterization result;
- screenshot path if available;
- accessibility snapshot status; and
- every deviation or unavailable check stated explicitly.

- [ ] **Step 7A: Refine prepend/append scope after cataloger acceptance**

- [ ] Add RED engine tests proving prepend/append can change every, first, or
  last selected value while text-match `occurrences` retains its existing
  per-value meaning.
- [ ] Add RED normalization/compiler tests proving missing `value_scope`
  defaults to `all` and an explicit value round-trips into the shared engine
  call.
- [ ] Add RED form tests for the separate **Which selected values should
  change?** control and its MARC-order warning.
- [ ] Implement the minimum `value_scope` validation, selection, authoring,
  compiler, summary, and preview-request plumbing needed to make those tests
  pass.
- [ ] Re-run the focused guided-engine, authoring, rendering, compiler, export,
  and workspace-mode Docker tests with every skip reported.

- [ ] **Step 8: Request independent code review**

Use `superpowers:requesting-code-review`. Provide the TASK-180 ticket, design,
plan, branch diff, focused output, full-suite output, native-contract output,
and browser evidence. Resolve every Critical and Important finding through a
new RED/GREEN cycle and rerun the affected focused tests plus the complete
suite.

- [ ] **Step 9: Complete ticket and parent checkpoint only after evidence**

Update TASK-180:

```markdown
Status: Completed

Plan:
- `docs/superpowers/plans/2026-07-30-task-180-core-structured-find-replace-authoring.md`

Final Evidence:
- Native contract: `test_checked_in_contract_matches_every_golden_definition`
- Browser acceptance:
  `docs/superpowers/evidence/task-180-guided-find-replace-browser-smoke.md`
- Independent review: no unresolved Critical or Important findings
```

Add **Focused Docker** and **Complete Docker** lines using the exact counts,
skip reasons, durations, and image identifier observed in Steps 2 and 4.
Do not change Status to Completed until those concrete values and every other
evidence line are present.

Add a TASK-180 completed checkpoint to TASK-174 without marking TASK-184 or
TASK-185 complete.

- [ ] **Step 10: Commit documentation and final evidence**

```bash
git add \
  docs/task-authoring-syntax.md \
  docs/superpowers/evidence/task-180-guided-find-replace-browser-smoke.md \
  .tickets/TASK-180-structured-find-replace-authoring.md \
  .tickets/TASK-174-smith-metadata-studio-open-task-migration.md
git commit -m "docs: complete core guided find replace"
```

- [ ] **Step 11: Verify the final branch diff**

```bash
git status --short
git log --oneline main..HEAD
git diff --check main...HEAD
git diff --stat main...HEAD
git diff --name-only main...HEAD
```

Expected: clean feature worktree; only TASK-180 files from the File Map;
TASK-184/TASK-185 remain Todo; no real corpus, vendor record, local database,
operation payload, secret, service, deployment, or ITS file appears.

---

## Plan Success Criteria

The implementation is ready to merge only when:

1. The 035 acceptance example produces
   `(SCTFEBA)9780020306634`, preserving the identifier.
2. Every valid combination in both compatibility tables has an intent-focused
   engine test.
3. Matched-text is the new-operation default; whole-value, prepend, and append
   are explicit.
4. First/all behavior is per selected value and covered for repeated fields
   and subfields.
5. Raw strings round-trip exactly with `match_mode="raw_regex"`.
6. Raw syntax/capture validation blocks save errors, but missing preview never
   blocks save.
7. Raw submission requires the same request, store identity, and store
   revision as a successful sandbox preview.
8. The compiler calls the transform re-export and adds no special import
   marker.
9. `guided_replace.py` imports no `marcedit_web.lib` module.
10. Existing saved operation, Quick Find/Replace, deterministic draft, Gemini,
    and AI validation behavior remains characterized and unchanged.
11. Empty-find imports are unresolved and marker-detectable saved empty-find
    operations are blocked by the composed submission preflight.
12. `^b` remains unresolved; TASK-184/TASK-185 behavior is not partially
    implemented.
13. The native compiler contract freshness test passes and its manifest has no
    branch diff.
14. Focused and complete Docker suites pass with every skip reported.
15. Synthetic browser acceptance passes.
16. Independent review has no unresolved Critical or Important findings.
17. Prepend and append can target every, first, or last selected value, with
    first/last explicitly defined by current MARC field/subfield order.
