# TASK-134 Diff Uploader Containment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release both Diff uploader widgets after every nonempty ingest round while preserving staged files safely on disk, invalidating stale review/output state, and giving users deterministic replacement, rejection, removal, and reset behavior.

**Architecture:** Keep TASK-134 as Streamlit containment. A new pure `marcedit_web.lib.diff_uploads` module owns collision-resistant disk staging and the small state machine around upload rounds; `6_Diff.py` owns only Streamlit rendering, audit emission, and reruns. Existing Diff comparison and output generation remain synchronous and unchanged.

**Tech Stack:** Python 3.9, Streamlit, pathlib/tempfile, pytest, existing audit and quota helpers

**Ticket:** [TASK-134](../../../.tickets/TASK-134-diff-uploader-widget-memory.md)

**Design:** [Approved TASK-134/TASK-162 design](../specs/2026-07-21-diff-ingress-safety-design.md)

## Global Constraints

- Python remains `>=3.9,<3.10`; do not use syntax introduced after Python 3.9.
- Each Diff source file remains capped at 2 GiB by `MARCEDIT_WEB_MAX_DIFF_BYTES`.
- Total staged bytes across old and new sides default to 8 GiB through `MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES=8589934592`.
- Physical admission requires the complete new candidate plus `MARCEDIT_WEB_DIFF_MIN_FREE_BYTES=1073741824`, even for replacement.
- At most 200 logical staged files exist across both sides. The unchanged
  render path opens roughly two descriptors per file (a handle and mmap), so
  200 leaves operating headroom under the expected 1,024-descriptor service
  limit without changing production units for containment code.
- A successful candidate is written and closed at a generated path before state changes; failed replacement preserves the prior entry and derived results.
- The last successfully written duplicate display name in upload order wins.
- Accepted add/replacement/removal invalidates all derived Diff review/output state; rejected-only rounds do not.
- Every nonempty side rotates its uploader key, including rejected-only and mixed rounds, then reruns once after both sides are processed.
- Persist at most 20 rejection entries with 255-character filenames and 512-character reasons for one post-ingest render; audit every rejection even when the UI summary is truncated. This acknowledgement is intentionally one-shot and is not repeated by the next pagination or form interaction.
- “Start over” removes the whole active Diff work tree before forgetting state. Do not add an abandoned-tree sweeper.
- Keep synchronous `diff_output_blobs` behavior unchanged; TASK-162 removes it later.
- Preserve unrelated workspace changes and untracked runtime data.
- Follow strict red-green-refactor: no production edit before its failing test is observed.
- Create every implementation commit on `task-134-diff-uploader`. Immediately
  after each `git commit`, verify `git branch --show-current`; if it reports
  `main`, stop and use the recovery procedure in Task 1 before continuing.
- Mark TASK-134 `In-Progress` only after the implementation worktree exists; mark it `Completed` only after all tests and independent code review pass.

## File Structure

- Modify `.tickets/TASK-134-diff-uploader-widget-memory.md`: lifecycle status and final evidence only.
- Modify `marcedit_web/lib/quotas.py`: containment staged-byte and free-disk settings.
- Create `marcedit_web/lib/diff_uploads.py`: deterministic upload-round staging, rejection persistence, invalidation, removal, and reset cleanup.
- Modify `marcedit_web/views/6_Diff.py`: dynamic widget keys, one-round orchestration, feedback, removal controls, and reset integration.
- Modify `tests/test_quotas.py`: exact containment defaults and overrides.
- Create `tests/test_diff_uploads.py`: intent-focused staging/state tests.
- Create `tests/test_diff_page_upload_contract.py`: page wiring guard against static keys and whole-body materialization.
- Modify `.env.example` and `docker-compose.pull.yml`: expose the two containment settings to production.
- Modify `tests/test_docker_compose_config.py` and `tests/test_deploy_units.py`: lock deployment defaults to the approved values.
- Modify `docs/deployment.md`: document active reset cleanup and the accepted temporary abandoned-tree tradeoff.

No queue, durable artifact, worker, ingress, download, merge, split, or TASK-163–166 implementation belongs in this plan.

---

### Task 1: Add the containment quota settings

**Files:**
- Modify: `.tickets/TASK-134-diff-uploader-widget-memory.md`
- Modify: `tests/test_quotas.py`
- Modify: `marcedit_web/lib/quotas.py`

**Interfaces:**
- Produces: `quotas.max_diff_staged_bytes() -> int`
- Produces: `quotas.diff_min_free_bytes() -> int`
- Preserves: `quotas.max_diff_bytes() -> int` and the removed per-side aggregate behavior

- [ ] **Step 1: Create the isolated worktree and mark the ticket In-Progress**

Use `superpowers:using-git-worktrees`. Create the branch from the current local
`HEAD`, not `origin/main`, because the remote branch does not yet contain this
ticket, design, plan, or their required Diff-page baseline:

```bash
git worktree add -b task-134-diff-uploader ../marcedit-web-task-134 HEAD
cd ../marcedit-web-task-134
test "$(git branch --show-current)" = "task-134-diff-uploader"
test -f docs/superpowers/plans/2026-07-21-task-134-diff-uploader-containment.md
test -f docs/superpowers/specs/2026-07-21-diff-ingress-safety-design.md
```

In that worktree, change only the ticket status line:

```markdown
Status: In-Progress
```

The commands above confirm the worktree contains the approved design and this
plan before production edits begin.

After every commit in this plan, run the branch assertion shown in that task.
If it reports `main`, do not make another edit or commit. From the accidental
main checkout, first verify both tracked worktree and index are clean, then
move that one commit to the feature branch and restore main:

```bash
task_accidental_sha="$(git rev-parse HEAD)"
git diff --quiet
git diff --cached --quiet
git -C ../marcedit-web-task-134 cherry-pick "$task_accidental_sha"
git reset --keep "$task_accidental_sha^"
cd ../marcedit-web-task-134
test "$(git branch --show-current)" = "task-134-diff-uploader"
```

If either clean-tree assertion fails, stop and inspect the changes instead of
resetting. This recovery is only for the immediately preceding accidental
commit.

- [ ] **Step 2: Write failing exact-default and override tests**

Append to `tests/test_quotas.py`:

```python
def test_diff_containment_defaults_leave_full_dump_headroom(monkeypatch):
    """Two 2-GiB full dumps retain another 4 GiB of staged headroom."""
    monkeypatch.delenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", raising=False)
    monkeypatch.delenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", raising=False)

    assert quotas.max_diff_staged_bytes() == 8 * 1024**3
    assert quotas.diff_min_free_bytes() == 1024**3


def test_diff_containment_settings_are_independently_overridable(monkeypatch):
    """Disk containment never reuses Home's session aggregate authority."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "9000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "700")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_SESSION_BYTES", "1")

    assert quotas.max_diff_staged_bytes() == 9000
    assert quotas.diff_min_free_bytes() == 700
```

- [ ] **Step 3: Run the tests and verify RED**

Run:

```bash
pytest tests/test_quotas.py::test_diff_containment_defaults_leave_full_dump_headroom tests/test_quotas.py::test_diff_containment_settings_are_independently_overridable -q
```

Expected: both fail with `AttributeError` because the two resolvers do not exist.

- [ ] **Step 4: Add only the two quota resolvers**

In `marcedit_web/lib/quotas.py`, add these defaults beside `_DEFAULT_DIFF_BYTES`:

```python
_DEFAULT_DIFF_STAGED_BYTES = 8 * 1024 * 1024 * 1024
_DEFAULT_DIFF_MIN_FREE_BYTES = 1 * 1024 * 1024 * 1024
```

Add these public functions immediately after `max_diff_bytes()`:

```python
def max_diff_staged_bytes() -> int:
    """Return the containment-only total staged bytes across both sides."""
    return _env_int(
        "MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES",
        _DEFAULT_DIFF_STAGED_BYTES,
    )


def diff_min_free_bytes() -> int:
    """Return free disk that must remain after admitting a Diff candidate."""
    return _env_int(
        "MARCEDIT_WEB_DIFF_MIN_FREE_BYTES",
        _DEFAULT_DIFF_MIN_FREE_BYTES,
    )
```

Do not call `check_session_aggregate()` from Diff.

- [ ] **Step 5: Run focused and existing quota tests**

Run:

```bash
pytest tests/test_quotas.py -q
```

Expected: all tests pass with no skips.

- [ ] **Step 6: Commit the quota unit**

```bash
git add .tickets/TASK-134-diff-uploader-widget-memory.md marcedit_web/lib/quotas.py tests/test_quotas.py
git commit -m "feat: add Diff staging containment limits"
test "$(git branch --show-current)" = "task-134-diff-uploader"
```

---

### Task 2: Build failure-atomic Diff staging

**Files:**
- Create: `tests/test_diff_uploads.py`
- Create: `marcedit_web/lib/diff_uploads.py`

**Interfaces:**
- Produces: `UploadEvent(accepted, side, filename, size, reason, limit)`
- Produces: `IngestOutcome(submitted_sides, events, changed)`
- Produces: `ensure_state(state)`, `uploader_key(state, side)`, `ingest_round(state, old_files, new_files, *, free_bytes=None)`
- Session storage remains `list[tuple[str, str]]` in `diff_old_buffers` and `diff_new_buffers`, so existing Diff callers do not change shape.

- [ ] **Step 1: Write streaming fakes and core failing tests**

Create `tests/test_diff_uploads.py` with these helpers and tests:

```python
from __future__ import annotations

import io
from pathlib import Path

import pytest

from marcedit_web.lib import diff_uploads


class StreamOnlyUpload(io.BytesIO):
    """Model Streamlit upload IO without allowing a second whole-body copy."""

    def __init__(self, name: str, data: bytes):
        super().__init__(data)
        self.name = name
        self.size = len(data)

    def getbuffer(self):
        raise AssertionError("Diff ingest must stream bounded reads")

    def getvalue(self):
        raise AssertionError("Diff ingest must stream bounded reads")

    def read(self, size=-1):
        assert size is not None and 0 < size <= 1024 * 1024
        return super().read(size)


class ExplodingUpload(StreamOnlyUpload):
    def read(self, size=-1):
        raise RuntimeError("reader failed unexpectedly")


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(diff_uploads.tempfile, "tempdir", str(tmp_path))
    value = {}
    diff_uploads.ensure_state(value)
    return value


def _room(_path: Path) -> int:
    return 10**12


def test_round_accumulates_files_and_rotates_only_submitted_side(
    state, monkeypatch,
):
    """Released widgets do not erase disk-backed files from earlier rounds."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")

    first = diff_uploads.ingest_round(
        state, [StreamOnlyUpload("a.mrc", b"aaa")], [], free_bytes=_room,
    )
    second = diff_uploads.ingest_round(
        state, [StreamOnlyUpload("b.mrc", b"bbbb")], [], free_bytes=_room,
    )

    assert first.submitted_sides == ("old",)
    assert second.submitted_sides == ("old",)
    assert diff_uploads.uploader_key(state, "old") == "diff_old_uploader_2"
    assert diff_uploads.uploader_key(state, "new") == "diff_new_uploader_0"
    assert [name for name, _ in state["diff_old_buffers"]] == ["a.mrc", "b.mrc"]
    assert all(Path(path).is_file() for _, path in state["diff_old_buffers"])


def test_equal_size_replacement_writes_new_bytes_and_removes_old_path(
    state, monkeypatch,
):
    """Equal size is never treated as proof that content is unchanged."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")
    diff_uploads.ingest_round(
        state, [StreamOnlyUpload("same.mrc", b"old")], [], free_bytes=_room,
    )
    old_path = Path(state["diff_old_buffers"][0][1])
    state["diff_result"] = {"stale": True}

    outcome = diff_uploads.ingest_round(
        state, [StreamOnlyUpload("same.mrc", b"new")], [], free_bytes=_room,
    )
    new_path = Path(state["diff_old_buffers"][0][1])

    assert outcome.changed is True
    assert new_path != old_path
    assert new_path.read_bytes() == b"new"
    assert not old_path.exists()
    assert state["diff_result"] is None


def test_replacement_charges_only_positive_logical_delta(state, monkeypatch):
    """A replacement is not charged as old bytes plus new logical bytes."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "5")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")
    diff_uploads.ingest_round(
        state, [StreamOnlyUpload("same.mrc", b"1234")], [], free_bytes=_room,
    )

    outcome = diff_uploads.ingest_round(
        state, [StreamOnlyUpload("same.mrc", b"12345")], [], free_bytes=_room,
    )

    assert outcome.events[0].accepted is True
    assert Path(state["diff_old_buffers"][0][1]).read_bytes() == b"12345"


def test_failed_replacement_preserves_prior_entry_and_results(
    state, monkeypatch,
):
    """Physical-candidate failure cannot destroy a valid logical file."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "10")
    diff_uploads.ingest_round(
        state, [StreamOnlyUpload("same.mrc", b"old")], [], free_bytes=_room,
    )
    prior = list(state["diff_old_buffers"])
    state["diff_result"] = {"kept": True}

    outcome = diff_uploads.ingest_round(
        state,
        [StreamOnlyUpload("same.mrc", b"new")],
        [],
        free_bytes=lambda _path: 12,
    )

    assert outcome.changed is False
    assert state["diff_old_buffers"] == prior
    assert Path(prior[0][1]).read_bytes() == b"old"
    assert state["diff_result"] == {"kept": True}
    assert outcome.events[0].accepted is False


def test_short_write_preserves_prior_entry(state, monkeypatch):
    """A declared-size mismatch never replaces the last valid candidate."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")
    diff_uploads.ingest_round(
        state, [StreamOnlyUpload("same.mrc", b"old")], [], free_bytes=_room,
    )
    prior = list(state["diff_old_buffers"])
    short = StreamOnlyUpload("same.mrc", b"new")
    short.size = 5

    outcome = diff_uploads.ingest_round(
        state, [short], [], free_bytes=_room,
    )

    assert outcome.events[0].accepted is False
    assert state["diff_old_buffers"] == prior
    assert Path(prior[0][1]).read_bytes() == b"old"


def test_write_all_retries_partial_filesystem_writes():
    """A short write return cannot silently truncate an accepted candidate."""
    class ShortWriter:
        def __init__(self):
            self.data = bytearray()

        def write(self, data):
            count = min(2, len(data))
            self.data.extend(bytes(data[:count]))
            return count

    writer = ShortWriter()

    diff_uploads._write_all(writer, b"abcdef")

    assert bytes(writer.data) == b"abcdef"


def test_closed_candidate_size_mismatch_preserves_prior(
    state, monkeypatch,
):
    """Closed-file size is verified independently of bytes read from upload."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")
    diff_uploads.ingest_round(
        state, [StreamOnlyUpload("same.mrc", b"old")], [], free_bytes=_room,
    )
    prior = list(state["diff_old_buffers"])
    monkeypatch.setattr(
        diff_uploads,
        "_write_all",
        lambda output, chunk: output.write(bytes(chunk[:-1])),
    )

    outcome = diff_uploads.ingest_round(
        state, [StreamOnlyUpload("same.mrc", b"new")], [], free_bytes=_room,
    )

    assert outcome.events[0].accepted is False
    assert state["diff_old_buffers"] == prior
    assert Path(prior[0][1]).read_bytes() == b"old"


def test_generated_paths_keep_sanitization_collisions_distinct(
    state, monkeypatch,
):
    """Display-name sanitization cannot alias two logical uploads."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")

    diff_uploads.ingest_round(
        state,
        [StreamOnlyUpload("a b.mrc", b"one"), StreamOnlyUpload("a_b.mrc", b"two")],
        [],
        free_bytes=_room,
    )

    entries = state["diff_old_buffers"]
    assert [name for name, _ in entries] == ["a b.mrc", "a_b.mrc"]
    assert len({path for _, path in entries}) == 2
    assert {Path(path).read_bytes() for _, path in entries} == {b"one", b"two"}


def test_last_successful_duplicate_wins_and_superseded_candidate_is_removed(
    state, monkeypatch,
):
    """One round resolves duplicate display names in upload order."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")

    outcome = diff_uploads.ingest_round(
        state,
        [StreamOnlyUpload("dup.mrc", b"first"), StreamOnlyUpload("dup.mrc", b"last")],
        [],
        free_bytes=_room,
    )

    assert len(state["diff_old_buffers"]) == 1
    assert Path(state["diff_old_buffers"][0][1]).read_bytes() == b"last"
    root = Path(state["diff_workdir_root"])
    assert list(root.rglob("*.mrc")) == [
        Path(state["diff_old_buffers"][0][1])
    ]
    assert [event.accepted for event in outcome.events] == [True, True]


def test_total_file_count_admission_spans_both_sides(state, monkeypatch):
    """The configured file-count containment spans old and new sides."""
    monkeypatch.setattr(diff_uploads, "MAX_STAGED_FILES", 2)
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")

    outcome = diff_uploads.ingest_round(
        state,
        [StreamOnlyUpload("old.mrc", b"123")],
        [StreamOnlyUpload("new.mrc", b"456"), StreamOnlyUpload("extra.mrc", b"7")],
        free_bytes=_room,
    )

    assert len(state["diff_old_buffers"]) == 1
    assert len(state["diff_new_buffers"]) == 1
    assert outcome.events[-1].accepted is False
    assert outcome.events[-1].reason.startswith("diff-staged-file-count")


def test_total_staged_byte_admission_spans_both_sides(state, monkeypatch):
    """One cross-side byte ceiling rejects before writing a partial candidate."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "5")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")

    outcome = diff_uploads.ingest_round(
        state,
        [StreamOnlyUpload("old.mrc", b"123")],
        [StreamOnlyUpload("new.mrc", b"456")],
        free_bytes=_room,
    )

    assert outcome.events[0].accepted is True
    assert outcome.events[1].accepted is False
    assert outcome.events[1].limit == 5
    assert state["diff_new_buffers"] in (None, [])
    root = Path(state["diff_workdir_root"])
    assert list(root.rglob("*.mrc")) == [
        Path(state["diff_old_buffers"][0][1])
    ]


def test_failed_later_duplicate_keeps_last_successful_occurrence(
    state, monkeypatch,
):
    """A rejected duplicate cannot erase an earlier success in the same round."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "4")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")

    outcome = diff_uploads.ingest_round(
        state,
        [StreamOnlyUpload("dup.mrc", b"good"), StreamOnlyUpload("dup.mrc", b"large")],
        [],
        free_bytes=_room,
    )

    assert [event.accepted for event in outcome.events] == [True, False]
    assert Path(state["diff_old_buffers"][0][1]).read_bytes() == b"good"


def test_ordinary_reader_failure_is_bounded_and_both_sides_rotate(
    state, monkeypatch,
):
    """One unexpected upload failure cannot pin either submitted widget."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")
    diff_uploads.ingest_round(
        state, [StreamOnlyUpload("prior.mrc", b"ok")], [], free_bytes=_room,
    )
    prior = list(state["diff_old_buffers"])
    state["diff_result"] = {"valid": True}
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "3")

    outcome = diff_uploads.ingest_round(
        state,
        [ExplodingUpload("broken.mrc", b"xx")],
        [StreamOnlyUpload("too-large.mrc", b"long")],
        free_bytes=_room,
    )

    assert [event.accepted for event in outcome.events] == [False, False]
    assert "reader failed unexpectedly" in outcome.events[0].reason
    assert state["diff_old_buffers"] == prior
    assert state["diff_result"] == {"valid": True}
    assert diff_uploads.uploader_key(state, "old") == "diff_old_uploader_2"
    assert diff_uploads.uploader_key(state, "new") == "diff_new_uploader_1"
```

- [ ] **Step 2: Run core staging tests and verify RED**

Run:

```bash
pytest tests/test_diff_uploads.py -q
```

Expected: collection fails because `marcedit_web.lib.diff_uploads` does not exist.

- [ ] **Step 3: Implement the staging data contract and admission helpers**

Create `marcedit_web/lib/diff_uploads.py` with these public types/constants and helper behavior:

```python
from __future__ import annotations

import hmac
import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, MutableMapping, Optional, Sequence

from . import quotas


CHUNK_BYTES = 1024 * 1024
MAX_STAGED_FILES = 200
MAX_REJECTIONS = 20
MAX_REJECTION_FILENAME_CHARS = 255
MAX_REJECTION_REASON_CHARS = 512
_BUFFER_KEYS = {"old": "diff_old_buffers", "new": "diff_new_buffers"}
_NONCE_KEYS = {"old": "diff_old_uploader_nonce", "new": "diff_new_uploader_nonce"}
_ROOT_TOKEN_KEY = "diff_workdir_token"
_ROOT_MARKER = ".marcedit-web-diff-owner"
_DERIVED_KEYS = (
    "diff_combined_suggestions",
    "diff_preview_matches",
    "diff_preview_specs",
    "diff_result",
    "diff_output_blobs",
)
DERIVED_STATE_KEYS = _DERIVED_KEYS


@dataclass(frozen=True)
class UploadEvent:
    accepted: bool
    side: str
    filename: str
    size: int
    reason: Optional[str] = None
    limit: Optional[int] = None


@dataclass(frozen=True)
class IngestOutcome:
    submitted_sides: tuple[str, ...]
    events: tuple[UploadEvent, ...]
    changed: bool


def ensure_state(state: MutableMapping) -> None:
    state.setdefault("diff_old_buffers", None)
    state.setdefault("diff_new_buffers", None)
    state.setdefault("diff_old_uploader_nonce", 0)
    state.setdefault("diff_new_uploader_nonce", 0)
    state.setdefault("diff_upload_rejections", None)


def invalidate_derived(state: MutableMapping) -> None:
    for key in DERIVED_STATE_KEYS:
        state[key] = None
    for key in list(state):
        if key.startswith("diff_page_"):
            state.pop(key, None)


def uploader_key(state: MutableMapping, side: str) -> str:
    return f"diff_{side}_uploader_{state[_NONCE_KEYS[side]]}"


def _entries(state: MutableMapping, side: str) -> list[tuple[str, str]]:
    return list(state.get(_BUFFER_KEYS[side]) or [])


def _entry_size(path: str) -> int:
    return Path(path).stat().st_size


def _staged_bytes(state: MutableMapping) -> int:
    return sum(
        _entry_size(path)
        for side in ("old", "new")
        for _, path in _entries(state, side)
    )


def _staged_count(state: MutableMapping) -> int:
    return sum(len(_entries(state, side)) for side in ("old", "new"))


def _upload_size(upload) -> int:
    size = getattr(upload, "size", None)
    if size is not None:
        return int(size)
    upload.seek(0, os.SEEK_END)
    size = upload.tell()
    upload.seek(0)
    return int(size)


def _root(state: MutableMapping) -> Path:
    current = state.get("diff_workdir_root")
    if current:
        return _owned_root(state)
    created = Path(tempfile.mkdtemp(prefix="marcedit-web-diff-"))
    token = secrets.token_hex(32)
    try:
        (created / _ROOT_MARKER).write_text(token, encoding="ascii")
    except Exception:
        shutil.rmtree(created)
        raise
    state["diff_workdir_root"] = str(created)
    state[_ROOT_TOKEN_KEY] = token
    return created


def _owned_root(state: MutableMapping) -> Path:
    raw_root = state.get("diff_workdir_root")
    token = state.get(_ROOT_TOKEN_KEY)
    if not raw_root or not token:
        raise OSError("Diff work directory ownership is missing")
    unresolved = Path(raw_root)
    if unresolved.is_symlink():
        raise OSError("refusing a symlinked Diff work directory")
    root = unresolved.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    marker = root / _ROOT_MARKER
    if root.parent != temp_root or not root.name.startswith("marcedit-web-diff-"):
        raise OSError("refusing an unexpected Diff work directory")
    if marker.is_symlink() or not marker.is_file():
        raise OSError("Diff work directory ownership marker is invalid")
    actual = marker.read_text(encoding="ascii")
    if not hmac.compare_digest(actual, str(token)):
        raise OSError("Diff work directory ownership marker does not match")
    return root


def _write_all(output, chunk: bytes) -> None:
    remaining = memoryview(chunk)
    while remaining:
        written = output.write(remaining)
        if written is None or written <= 0:
            raise OSError("candidate write made no progress")
        remaining = remaining[written:]


def _write_candidate(upload, directory: Path, expected_size: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix="upload-", suffix=".mrc", dir=directory)
    candidate = Path(raw_path)
    total = 0
    try:
        upload.seek(0)
        with os.fdopen(fd, "wb") as output:
            while True:
                chunk = upload.read(CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected_size:
                    raise OSError("upload exceeded its declared size")
                _write_all(output, chunk)
            output.flush()
            os.fsync(output.fileno())
        if total != expected_size:
            raise OSError(
                f"upload ended at {total} bytes; expected {expected_size}"
            )
        if candidate.stat().st_size != expected_size:
            raise OSError(
                "candidate file size does not match the declared upload size"
            )
        return candidate
    except Exception:
        candidate.unlink(missing_ok=True)
        raise
```

Add the admission and replacement functions exactly as follows. Never derive a path from the display filename:

```python
def _default_free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _existing_entry(
    state: MutableMapping,
    side: str,
    filename: str,
) -> Optional[tuple[str, str]]:
    return next(
        (item for item in _entries(state, side) if item[0] == filename),
        None,
    )


def _admit(
    state: MutableMapping,
    side: str,
    filename: str,
    size: int,
    free_bytes: Callable[[Path], int],
) -> Path:
    quotas.check_upload(size, kind="diff")
    prior = _existing_entry(state, side, filename)
    proposed_count = _staged_count(state) + (0 if prior else 1)
    if proposed_count > MAX_STAGED_FILES:
        raise OSError(
            f"diff-staged-file-count {proposed_count} exceeds "
            f"limit {MAX_STAGED_FILES}"
        )
    prior_size = _entry_size(prior[1]) if prior else 0
    proposed_bytes = _staged_bytes(state) - prior_size + size
    staged_limit = quotas.max_diff_staged_bytes()
    if proposed_bytes > staged_limit:
        raise quotas.QuotaExceeded(
            "diff-staged",
            proposed_bytes,
            staged_limit,
        )
    root = _root(state)
    required_free = size + quotas.diff_min_free_bytes()
    available = free_bytes(root)
    if available < required_free:
        raise quotas.QuotaExceeded(
            "diff-free-disk",
            required_free,
            available,
        )
    return root / side


def _replace(
    state: MutableMapping,
    side: str,
    upload,
    filename: str,
    size: int,
    directory: Path,
) -> None:
    key = _BUFFER_KEYS[side]
    before = _entries(state, side)
    prior = next((item for item in before if item[0] == filename), None)
    candidate = _write_candidate(upload, directory, size)
    after = [item for item in before if item[0] != filename]
    after.append((filename, str(candidate)))
    state[key] = after
    if prior is None:
        return
    try:
        Path(prior[1]).unlink()
    except OSError:
        state[key] = before
        candidate.unlink(missing_ok=True)
        raise
```

Add the bounded summary and complete round implementation:

```python
def _bounded_rejections(events: list[UploadEvent]) -> Optional[dict]:
    rejected = [event for event in events if not event.accepted]
    if not rejected:
        return None
    entries = [
        {
            "side": event.side,
            "filename": event.filename[:MAX_REJECTION_FILENAME_CHARS],
            "reason": (event.reason or "rejected")[:MAX_REJECTION_REASON_CHARS],
        }
        for event in rejected[:MAX_REJECTIONS]
    ]
    return {"entries": entries, "omitted": len(rejected) - len(entries)}


def ingest_round(
    state: MutableMapping,
    old_files: Sequence,
    new_files: Sequence,
    *,
    free_bytes: Optional[Callable[[Path], int]] = None,
) -> IngestOutcome:
    ensure_state(state)
    batches = (("old", list(old_files)), ("new", list(new_files)))
    submitted = tuple(side for side, files in batches if files)
    if not submitted:
        return IngestOutcome((), (), False)

    disk_free = free_bytes or _default_free_bytes
    events: list[UploadEvent] = []
    changed = False
    for side, files in batches:
        for upload in files:
            filename = str(getattr(upload, "name", "upload.mrc"))
            size = 0
            try:
                size = _upload_size(upload)
                directory = _admit(
                    state,
                    side,
                    filename,
                    size,
                    disk_free,
                )
                _replace(
                    state,
                    side,
                    upload,
                    filename,
                    size,
                    directory,
                )
            except Exception as exc:
                events.append(
                    UploadEvent(
                        accepted=False,
                        side=side,
                        filename=filename,
                        size=size,
                        reason=str(exc),
                        limit=(
                            exc.limit
                            if isinstance(exc, quotas.QuotaExceeded)
                            else None
                        ),
                    )
                )
            else:
                changed = True
                events.append(
                    UploadEvent(
                        accepted=True,
                        side=side,
                        filename=filename,
                        size=size,
                    )
                )

    if changed:
        invalidate_derived(state)
    state["diff_upload_rejections"] = _bounded_rejections(events)
    for side in submitted:
        nonce_key = _NONCE_KEYS[side]
        state[nonce_key] += 1
    return IngestOutcome(submitted, tuple(events), changed)
```

- [ ] **Step 4: Run the staging tests and verify GREEN**

Run:

```bash
pytest tests/test_diff_uploads.py -q
```

Expected: all thirteen tests pass with no skips.

- [ ] **Step 5: Commit failure-atomic staging**

```bash
git add marcedit_web/lib/diff_uploads.py tests/test_diff_uploads.py
git commit -m "feat: stage Diff upload rounds atomically"
test "$(git branch --show-current)" = "task-134-diff-uploader"
```

---

### Task 3: Complete state invalidation, rejection, removal, and reset behavior

**Files:**
- Modify: `tests/test_diff_uploads.py`
- Modify: `marcedit_web/lib/diff_uploads.py`

**Interfaces:**
- Produces: `pop_rejection_summary(state) -> Optional[dict]`
- Produces: `remove_staged_file(state, side, filename) -> None`
- Produces: `cleanup_workdir(state) -> None`
- Produces: `invalidate_derived(state) -> None`
- Produces: `complete_round(outcome, *, user, audit, rerun) -> None`

- [ ] **Step 1: Add failing lifecycle tests**

Append to `tests/test_diff_uploads.py`:

```python
def test_mixed_round_invalidates_all_derived_state_and_bounds_feedback(
    state, monkeypatch,
):
    """Accepted bytes invalidate caches; all rejections are still auditable."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "3")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")
    for key in diff_uploads.DERIVED_STATE_KEYS:
        state[key] = {"stale": True}
    state["diff_page_changed"] = 4
    uploads = [StreamOnlyUpload("ok.mrc", b"ok")]
    uploads.extend(
        StreamOnlyUpload("x" * 300 + str(index), b"large")
        for index in range(25)
    )

    outcome = diff_uploads.ingest_round(
        state, uploads, [], free_bytes=_room,
    )
    summary = diff_uploads.pop_rejection_summary(state)

    assert outcome.changed is True
    assert len([event for event in outcome.events if not event.accepted]) == 25
    assert all(state[key] is None for key in diff_uploads.DERIVED_STATE_KEYS)
    assert "diff_page_changed" not in state
    assert len(summary["entries"]) == 20
    assert summary["omitted"] == 5
    assert all(len(item["filename"]) <= 255 for item in summary["entries"])
    assert all(len(item["reason"]) <= 512 for item in summary["entries"])
    assert diff_uploads.pop_rejection_summary(state) is None


def test_rejected_only_round_rotates_without_invalidating_results(
    state, monkeypatch,
):
    """Rejected upload bytes are released without destroying valid review."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "1")
    state["diff_result"] = {"valid": True}

    outcome = diff_uploads.ingest_round(
        state, [], [StreamOnlyUpload("bad.mrc", b"xx")], free_bytes=_room,
    )

    assert outcome.changed is False
    assert diff_uploads.uploader_key(state, "new") == "diff_new_uploader_1"
    assert state["diff_result"] == {"valid": True}
    assert diff_uploads.pop_rejection_summary(state)["entries"][0]["filename"] == "bad.mrc"


def test_remove_one_file_unlinks_only_it_and_invalidates(state, monkeypatch):
    """Per-file removal preserves unrelated staged work."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")
    diff_uploads.ingest_round(
        state,
        [StreamOnlyUpload("keep.mrc", b"keep"), StreamOnlyUpload("drop.mrc", b"drop")],
        [],
        free_bytes=_room,
    )
    dropped = Path(dict(state["diff_old_buffers"])["drop.mrc"])
    state["diff_output_blobs"] = {"stale": True}

    diff_uploads.remove_staged_file(state, "old", "drop.mrc")

    assert not dropped.exists()
    assert [name for name, _ in state["diff_old_buffers"]] == ["keep.mrc"]
    assert state["diff_output_blobs"] is None


def test_cleanup_workdir_recursively_removes_active_tree(state, monkeypatch):
    """Start over removes staged bytes before forgetting their root."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")
    diff_uploads.ingest_round(
        state, [StreamOnlyUpload("old.mrc", b"old")], [], free_bytes=_room,
    )
    root = Path(state["diff_workdir_root"])

    diff_uploads.cleanup_workdir(state)

    assert not root.exists()
    assert "diff_workdir_root" not in state
    assert "diff_workdir_token" not in state


def test_cleanup_refuses_temp_root_itself(state, tmp_path):
    """Corrupted session state can never make reset delete the temp root."""
    state["diff_workdir_root"] = str(tmp_path)
    state["diff_workdir_token"] = "forged"

    with pytest.raises(OSError, match="refusing|ownership"):
        diff_uploads.cleanup_workdir(state)

    assert tmp_path.exists()


def test_cleanup_refuses_prefixed_tree_outside_direct_temp_root(state, tmp_path):
    """A matching basename outside the owned root boundary is insufficient."""
    outside = tmp_path / "nested" / "marcedit-web-diff-outside"
    outside.mkdir(parents=True)
    (outside / ".marcedit-web-diff-owner").write_text("token")
    state["diff_workdir_root"] = str(outside)
    state["diff_workdir_token"] = "token"

    with pytest.raises(OSError, match="unexpected"):
        diff_uploads.cleanup_workdir(state)

    assert outside.exists()


def test_cleanup_refuses_sibling_with_wrong_ownership_marker(state, tmp_path):
    """A sibling's predictable prefix cannot authorize recursive deletion."""
    sibling = tmp_path / "marcedit-web-diff-sibling"
    sibling.mkdir()
    (sibling / ".marcedit-web-diff-owner").write_text("other")
    state["diff_workdir_root"] = str(sibling)
    state["diff_workdir_token"] = "expected"

    with pytest.raises(OSError, match="does not match"):
        diff_uploads.cleanup_workdir(state)

    assert sibling.exists()


def test_cleanup_refuses_symlink_substitution(state, monkeypatch):
    """Replacing an owned root with a symlink cannot redirect recursive reset."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "100")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")
    diff_uploads.ingest_round(
        state, [StreamOnlyUpload("old.mrc", b"old")], [], free_bytes=_room,
    )
    root = Path(state["diff_workdir_root"])
    real = root.with_name(root.name + "-real")
    root.rename(real)
    root.symlink_to(real, target_is_directory=True)

    with pytest.raises(OSError, match="symlinked"):
        diff_uploads.cleanup_workdir(state)

    assert real.exists()
    root.unlink()


def test_complete_round_audits_every_event_and_reruns_once(
    state, monkeypatch,
):
    """UI truncation never truncates audit, and both sides share one rerun."""
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_BYTES", "3")
    monkeypatch.setenv("MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES", "1000")
    monkeypatch.setenv("MARCEDIT_WEB_DIFF_MIN_FREE_BYTES", "0")
    old_files = [StreamOnlyUpload("old.mrc", b"ok")]
    old_files.extend(
        StreamOnlyUpload(f"bad-{index}.mrc", b"large")
        for index in range(25)
    )
    outcome = diff_uploads.ingest_round(
        state,
        old_files,
        [StreamOnlyUpload("new.mrc", b"new")],
        free_bytes=_room,
    )
    audits = []
    reruns = []

    diff_uploads.complete_round(
        outcome,
        user="cataloger@example.edu",
        audit=lambda kind, **fields: audits.append((kind, fields)),
        rerun=lambda: reruns.append(True),
    )
    summary = diff_uploads.pop_rejection_summary(state)

    assert len(audits) == 27
    assert [kind for kind, _ in audits].count("upload-accepted") == 2
    assert [kind for kind, _ in audits].count("upload-rejected") == 25
    assert all(fields["user"] == "cataloger@example.edu" for _, fields in audits)
    assert reruns == [True]
    assert len(summary["entries"]) == 20
    assert summary["omitted"] == 5
    assert diff_uploads.pop_rejection_summary(state) is None
```

- [ ] **Step 2: Run lifecycle tests and verify RED**

Run:

```bash
pytest tests/test_diff_uploads.py -q
```

Expected: the nine new tests fail because the lifecycle APIs/public key tuple are missing or incomplete.

- [ ] **Step 3: Implement exact lifecycle behavior**

Add these functions to `diff_uploads.py`:

```python
def pop_rejection_summary(state: MutableMapping) -> Optional[dict]:
    return state.pop("diff_upload_rejections", None)


def complete_round(
    outcome: IngestOutcome,
    *,
    user: str,
    audit,
    rerun,
) -> None:
    for event in outcome.events:
        fields = {
            "user": user,
            "source": "diff",
            "side": event.side,
            "filename": event.filename,
            "size": event.size,
        }
        if event.accepted:
            audit("upload-accepted", **fields)
        else:
            fields["reason"] = event.reason
            if event.limit is not None:
                fields["limit"] = event.limit
            audit("upload-rejected", **fields)
    if outcome.submitted_sides:
        rerun()


def remove_staged_file(
    state: MutableMapping,
    side: str,
    filename: str,
) -> None:
    entries = _entries(state, side)
    match = next((item for item in entries if item[0] == filename), None)
    if match is None:
        raise KeyError(filename)
    root = _owned_root(state)
    path = Path(match[1]).resolve()
    path.relative_to(root)
    path.unlink()
    state[_BUFFER_KEYS[side]] = [item for item in entries if item != match]
    invalidate_derived(state)


def cleanup_workdir(state: MutableMapping) -> None:
    raw_root = state.get("diff_workdir_root")
    if not raw_root:
        return
    root = _owned_root(state)
    shutil.rmtree(root)
    state.pop("diff_workdir_root", None)
    state.pop(_ROOT_TOKEN_KEY, None)
```

- [ ] **Step 4: Run all staging lifecycle tests**

Run:

```bash
pytest tests/test_diff_uploads.py -q
```

Expected: all tests pass with no skips.

- [ ] **Step 5: Commit the lifecycle unit**

```bash
git add marcedit_web/lib/diff_uploads.py tests/test_diff_uploads.py
git commit -m "feat: manage Diff staged-file lifecycle"
test "$(git branch --show-current)" = "task-134-diff-uploader"
```

---

### Task 4: Wire rotating widgets and per-file controls into the Diff page

**Files:**
- Create: `tests/test_diff_page_upload_contract.py`
- Modify: `marcedit_web/views/6_Diff.py`

**Interfaces:**
- Consumes all Task 2/3 `diff_uploads` interfaces.
- Preserves `old_bufs` and `new_bufs` as `list[tuple[str, str]]` for `_open_buffers()` and all downstream Diff steps.

- [ ] **Step 1: Write a failing page-contract test**

Create `tests/test_diff_page_upload_contract.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path


DIFF_PAGE = Path("marcedit_web/views/6_Diff.py")


def test_diff_page_uses_rotating_upload_contract_without_materializing():
    """Widget release must be wired to the tested staging state machine."""
    source = DIFF_PAGE.read_text()
    tree = ast.parse(source)
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert "getbuffer" not in attributes
    assert "_read_uploaded" not in source
    assert "diff_uploads.uploader_key" in source
    assert "diff_uploads.ingest_round" in source
    assert "diff_uploads.complete_round" in source
    assert "diff_uploads.pop_rejection_summary" in source
    assert "diff_uploads.remove_staged_file" in source
    assert "diff_uploads.cleanup_workdir" in source
```

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```bash
pytest tests/test_diff_page_upload_contract.py -q
```

Expected: failure because the page still defines `_read_uploaded`, calls `getbuffer()`, and uses static uploader keys.

- [ ] **Step 3: Replace only the upload/reset section**

In `6_Diff.py`:

1. Remove unused `io`, `logging`, `re`, `tempfile`, `_FILENAME_SAFE_RE`,
   `_safe_filename`, `_diff_workdir`, `_read_uploaded`, and `logger`. Keep the
   direct `audit_event` import for the completion helper call below.
2. Replace the current library import with:

```python
from marcedit_web.lib import diff_uploads, marc_diff, session
```

   `quotas` has no remaining page call after `_read_uploaded` is removed.
3. Call `diff_uploads.ensure_state(st.session_state)` from `_init_diff_state()`.
4. Replace `_reset_diff()` with this version so cleanup occurs before state is
   forgotten and `OSError` reaches the sidebar handler:

```python
def _reset_diff() -> None:
    """Remove active Diff files and clear only the Diff workflow state."""
    diff_uploads.cleanup_workdir(st.session_state)
    for key in list(st.session_state.keys()):
        if key.startswith("diff_") or key.startswith("diff_page_"):
            del st.session_state[key]
    _init_diff_state()
```
5. Change the sidebar button to show the bounded error and skip rerun on cleanup failure.

Use this sidebar shape:

```python
    if st.button("Start over (clear Diff uploads)"):
        try:
            _reset_diff()
        except OSError as exc:
            st.error(f"Could not remove Diff working files: {exc}")
        else:
            st.rerun()
```

Render and consume rejection state before the uploaders:

```python
rejection_summary = diff_uploads.pop_rejection_summary(st.session_state)
if rejection_summary:
    for item in rejection_summary["entries"]:
        st.error(f"`{item['filename']}` rejected: {item['reason']}")
    if rejection_summary["omitted"]:
        st.error(
            f"{rejection_summary['omitted']} additional rejection(s) were "
            "recorded in the audit log."
        )
```

Give each uploader its rotating key:

```python
        key=diff_uploads.uploader_key(st.session_state, "old"),
```

and:

```python
        key=diff_uploads.uploader_key(st.session_state, "new"),
```

Process both sides once, then delegate complete audit emission and the single
rerun to the behaviorally tested helper:

```python
if old_files or new_files:
    outcome = diff_uploads.ingest_round(
        st.session_state,
        old_files or [],
        new_files or [],
    )
    diff_uploads.complete_round(
        outcome,
        user=user,
        audit=audit_event,
        rerun=st.rerun,
    )
```

Keep the `audit_event` import because this loop now owns audit emission.

Add one compact removal control per nonempty side after the size summaries:

```python
def _render_file_removal(side: str, entries: list[tuple[str, str]]) -> None:
    if not entries:
        return
    label = "Original" if side == "old" else "New"
    choice = st.selectbox(
        f"Remove one {label.lower()} file",
        [name for name, _ in entries],
        key=f"diff_{side}_remove_choice",
    )
    if st.button(f"Remove {label.lower()} file", key=f"diff_{side}_remove"):
        try:
            diff_uploads.remove_staged_file(st.session_state, side, choice)
        except (KeyError, OSError, ValueError) as exc:
            st.error(f"Could not remove `{choice}`: {exc}")
        else:
            st.session_state.pop(f"diff_{side}_remove_choice", None)
            st.rerun()
```

Call it for both sides before the `if not (old_bufs and new_bufs)` gate. Do not change suggestions, matching, comparison, review, or output-generation code.

- [ ] **Step 4: Run page and staging contract tests**

Run:

```bash
pytest tests/test_diff_page_upload_contract.py tests/test_diff_uploads.py tests/test_marc_diff.py -q
```

Expected: all pass with no skips.

- [ ] **Step 5: Compile the changed modules**

Run:

```bash
python -m py_compile marcedit_web/lib/diff_uploads.py marcedit_web/views/6_Diff.py
```

Expected: exit 0 with no output.

- [ ] **Step 6: Commit page integration**

```bash
git add marcedit_web/views/6_Diff.py tests/test_diff_page_upload_contract.py
git commit -m "feat: rotate Diff upload widgets after ingest"
test "$(git branch --show-current)" = "task-134-diff-uploader"
```

---

### Task 5: Expose production settings and document temporary cleanup ownership

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.pull.yml`
- Modify: `tests/test_docker_compose_config.py`
- Modify: `tests/test_deploy_units.py`
- Modify: `docs/deployment.md`

**Interfaces:**
- Produces production defaults `MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES=8589934592` and `MARCEDIT_WEB_DIFF_MIN_FREE_BYTES=1073741824` for the private Streamlit service.
- Preserves the existing 2 GiB per-file Diff cap and 2048 MiB framework cap.

- [ ] **Step 1: Write failing deployment contract tests**

Append to `tests/test_docker_compose_config.py`:

```python
def test_pull_compose_passes_diff_containment_limits_to_private_app():
    """Published private deploys receive the approved staged-disk guardrails."""
    compose = _build_context_file("docker-compose.pull.yml")
    app = compose.split("  marcedit-web-worker:", 1)[0]

    assert (
        'MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES: '
        '"${MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES:-8589934592}"'
    ) in app
    assert (
        'MARCEDIT_WEB_DIFF_MIN_FREE_BYTES: '
        '"${MARCEDIT_WEB_DIFF_MIN_FREE_BYTES:-1073741824}"'
    ) in app
```

Append to `tests/test_deploy_units.py`:

```python
def test_native_env_template_declares_diff_containment_limits():
    """Native systemd receives the same staged-byte and free-disk defaults."""
    template = _repo_file(".env.example")

    assert "MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES=8589934592" in template
    assert "MARCEDIT_WEB_DIFF_MIN_FREE_BYTES=1073741824" in template
```

- [ ] **Step 2: Run deployment tests and verify RED**

Run:

```bash
pytest tests/test_docker_compose_config.py::test_pull_compose_passes_diff_containment_limits_to_private_app tests/test_deploy_units.py::test_native_env_template_declares_diff_containment_limits -q
```

Expected: both fail because neither deployment surface declares the settings.

- [ ] **Step 3: Add exact configuration and cleanup documentation**

Under the Diff upload cap in `.env.example`, add:

```dotenv
MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES=8589934592
MARCEDIT_WEB_DIFF_MIN_FREE_BYTES=1073741824
```

In only the `marcedit-web` service environment of `docker-compose.pull.yml`, add:

```yaml
      MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES: "${MARCEDIT_WEB_MAX_DIFF_STAGED_BYTES:-8589934592}"
      MARCEDIT_WEB_DIFF_MIN_FREE_BYTES: "${MARCEDIT_WEB_DIFF_MIN_FREE_BYTES:-1073741824}"
```

Replace the current blind runtime-temp cleanup recommendation in `docs/deployment.md` with this containment statement:

```markdown
TASK-134 removes the active Diff work tree when the cataloger selects **Start
over**, but intentionally does not sweep abandoned Streamlit session trees.
Safely proving that a tree is inactive would add locking machinery that the
durable TASK-164/TASK-165 cutover removes. For native systemd,
`PrivateTmp=true` means a controlled private-service restart recreates the
service's private temporary namespace. For Compose, use container
recreation/removal rather than `docker restart`; a restart may retain the
container writable layer. Until durable ingress ships, monitor temporary-disk
use and schedule the appropriate native-service restart or Compose recreation
during a maintenance window. Do not run a blind age-based `rm -rf` against
these trees while the service is active.
```

- [ ] **Step 4: Run deployment-focused tests**

Run:

```bash
pytest tests/test_docker_compose_config.py tests/test_deploy_units.py -q
```

Expected: all pass; report any Docker-dependent skips explicitly.

- [ ] **Step 5: Commit deployment documentation**

```bash
git add .env.example docker-compose.pull.yml tests/test_docker_compose_config.py tests/test_deploy_units.py docs/deployment.md
git commit -m "docs: configure Diff staging containment"
test "$(git branch --show-current)" = "task-134-diff-uploader"
```

---

### Task 6: Verify TASK-134 and close only after independent review

**Files:**
- Modify: `.tickets/TASK-134-diff-uploader-widget-memory.md`

**Interfaces:**
- No new production interface.
- Produces complete test/review evidence in the local ticket.

- [ ] **Step 1: Run focused TASK-134 verification**

Run:

```bash
pytest tests/test_quotas.py tests/test_diff_uploads.py tests/test_diff_page_upload_contract.py tests/test_marc_diff.py tests/test_docker_compose_config.py tests/test_deploy_units.py -q
```

Expected: all runnable tests pass. List every environment-dependent skip by test name and reason; do not summarize a skipped suite as passing.

- [ ] **Step 2: Run the complete suite**

Run:

```bash
pytest -q
```

Expected: zero failures. Report the exact passed/skipped counts.

- [ ] **Step 3: Run static and diff checks**

Run:

```bash
python -m compileall -q marcedit_web tests
git diff --check
git status --short
```

Expected: compile and whitespace checks exit 0; status contains only TASK-134 files plus any pre-existing unrelated paths.

- [ ] **Step 4: Run the authenticated browser smoke test at safe fixture sizes**

Through both Diff uploaders, verify:

1. accepted old and new files remain listed after widget rotation;
2. a second round accumulates a new filename;
3. same-name/same-size replacement changes subsequent Diff counts;
4. one accepted plus one rejected file shows the rejection once and retains the accepted file;
5. rejected-only upload releases its widget without invalidating an existing result;
6. per-file removal invalidates the result and leaves unrelated files;
7. **Start over** removes the active work tree and resets only Diff state.

Do not use a 2 GiB fixture in this TASK-134 smoke test; the ticket explicitly does not make Streamlit's ingress peak safe.

- [ ] **Step 5: Request independent code review**

Use `superpowers:requesting-code-review`. Resolve every Critical and Important finding, rerun affected focused tests, then rerun `git diff --check`.

- [ ] **Step 6: Record evidence and complete the ticket**

Add the exact focused/full test counts, skips, browser evidence, and review verdict to TASK-134. Change status to:

```markdown
Status: Completed
```

only after all criteria pass.

- [ ] **Step 7: Commit completion evidence**

```bash
git add .tickets/TASK-134-diff-uploader-widget-memory.md
git commit -m "docs: complete TASK-134 evidence"
test "$(git branch --show-current)" = "task-134-diff-uploader"
```

Do not push or deploy without a separate explicit production-safety check and user authorization.
