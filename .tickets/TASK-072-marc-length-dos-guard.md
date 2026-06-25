# TASK-072 — Guard against non-advancing MARC record length (CPU DoS)

**Status:** Completed
**Priority:** Tier 0 — Security (urgent)
**Branch:** task-072-marc-length-dos (worktree .worktrees/task-072-marc-dos)
**Source:** Deep code audit 2026-06-17 — finding S4 (MEDIUM, confirmed)

## Title

Reject MARC records whose declared length cannot advance the read cursor, so a
crafted file can't wedge a worker thread in an infinite loop.

## Scope

- `lib/marc_diff.py:383-397` `_iter_records` reads a 5-byte length; a leader of
  `00000` yields `pos += 0` forever, pinning the Streamlit worker thread at
  100% CPU on the single-process server. The `except ValueError` never fires
  because no exception is raised.
- After computing length, raise/skip when `length < 24` (MARC leader minimum) —
  routing it to the already-handled malformed-record path.
- Verify callers treat it as a malformed record without an unhandled
  exception: `record_store._index_bytes`, `marc_diff.index_buffer:412`,
  `render/dedupe.py:179`.

## Success Criteria

1. A 10-byte blob with leader length `00000` returns/raises promptly — a test
   asserts bounded iterations/time (no infinite loop).
2. Valid multi-record files still iterate correctly.
3. Uploading the crafted file surfaces a "malformed record" error rather than
   wedging the worker thread.
4. Focused tests and the Docker test suite pass before completion.

## Resolution (2026-06-17)

Added a guard in `marc_diff._iter_records`: a declared length below the 24-byte
leader minimum (`length < LEADER_LEN`) raises `ValueError`, identical to the
existing truncated/short-read handling. This eliminates the `00000` infinite
loop AND a second latent variant the reviewer caught — a negative length
(`int(b"-0001") == -1`) that walked `pos` backward into another infinite loop.

Caller routing (all funnel through `_iter_records`): the upload DoS vector
(`record_store._index_bytes`) catches the `ValueError` → one malformed record,
returns promptly (verified: `from_bytes(b"00000abcde")` → `malformed_count==1`);
`dedupe` (try/except) and `task_diff._iter_records_safe` already catch.

KNOWN, OUT-OF-SCOPE (Rule 12): the Diff page (`views/6_Diff.py:714/716`, and
`552`/`648`) calls `index_buffers`/sampling without try/except, so a crafted
blob there surfaces an uncaught Streamlit error banner rather than a graceful
"malformed record" message. This is PRE-EXISTING (truncated input already raised
there before this change); the fix converts that path from a hang to an error
banner (strictly better) but does not add graceful handling. Candidate
follow-up: a Diff-page malformed-input UX ticket.

Tests: `tests/test_marc_diff.py` (zero / sub-leader / negative lengths raise;
valid record still iterates) + `tests/test_record_store.py`
(`from_bytes` zero-length → malformed). Verified falsifiable (removing the guard
hangs the zero-length tests under `--timeout`). Full Docker suite: 691 passed.
Independent code review: approve-with-nits; negative-length test added per the
review. Commit on branch `task-072-marc-length-dos`.
