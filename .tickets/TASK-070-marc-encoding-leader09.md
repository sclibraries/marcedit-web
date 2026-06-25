# TASK-070 — Declare UTF-8 in leader/09 on every record write

**Status:** Completed — closed as invalid bug; regression guard added (see Resolution)
**Priority:** Tier 0 — Correctness (highest daily-use risk)
**Branch:** task-070-encoding-leader09 (worktree .worktrees/task-070-encoding); commit e1d2d58

## Finding (2026-06-17) — bug does not exist in the pinned pymarc

Verified against pymarc 5.3.1 (the project pins `pymarc>=5.1.2,<6`):
`pymarc.Record.as_marc()` runs, before serializing —
`if self.to_unicode: self.leader.coding_scheme = "a"` — and chooses
`encoding = "utf-8" if self.leader[9] == "a" or self.force_utf8 else "iso8859-1"`.
`MARCReader(to_unicode=True)` yields records with `record.to_unicode == True`,
and a fresh `pymarc.Record()` also defaults `to_unicode=True`.

Empirical round-trip: a record whose in-memory leader/09 declared MARC-8 (`' '`)
was re-emitted with leader/09 = `'a'` and UTF-8 bytes, with NO code change.
`MARCWriter.write()` calls `record.as_marc()`, so every write sink is covered.
Repo sweep confirms there is no `to_unicode=False`, no `force_utf8`, and no
`RawField` path that could bypass this. The corruption scenario the audit
described therefore cannot occur on the supported dependency range.

Root cause of the false alarm: the audit's horizon critic (this item was NOT
adversarially verified, unlike the security findings) assumed pymarc preserves
leader/09 verbatim on write; pymarc 5.x actively rewrites it from the
`to_unicode` flag.

## Resolution (2026-06-17)

Closed as an invalid bug (no fix needed on the pinned pymarc). Re-scoped to a
regression GUARD instead: `tests/test_marc_encoding.py` (5 tests) pins the
invariant "app-emitted records declare UTF-8 (leader/09=='a')" across the real
emit sinks — `RecordStore.to_mrc_bytes`/`write_mrc_to`/`from_records` and the
converters `.mrk` export — so a future pymarc major bump (the `<6` pin) or an
accidental `to_unicode=False` is caught. Each guard starts from a MARC-8-declared
input and was verified falsifiable (a simulated `to_unicode=False` regression
makes it fail). Full Docker suite: 686 passed. Independent code review:
approve-with-nits; nits addressed (docstring accuracy, stronger mrk
up-declaration guard, added `write_mrc_to` coverage). No production code changed.
**Source:** Deep code audit 2026-06-17 — horizon critic #1 (confirmed mechanism)

## Title

Set leader position 9 to `a` when emitting records read with `to_unicode=True`,
so MARC-8 input is no longer silently re-emitted as UTF-8 bytes that still
declare MARC-8.

## Scope

- Every read path uses `MARCReader(to_unicode=True)` (decodes MARC-8 to
  Unicode); every write path re-emits as UTF-8 but never updates leader/09.
- Add a single shared write helper (or wrap `MARCWriter`) that sets
  `record.leader[9] = 'a'` on emit; make it idempotent for already-UTF-8 and
  pure-ASCII records.
- Apply on all write sinks: `lib/sandbox.py:142`, `lib/converters.py:309`,
  `lib/batch_replace.py:242`, `lib/record_store.py:151/295/314`,
  `render/marc_tools.py:113`, `render/find.py:326`.

## Success Criteria

1. A MARC-8 record with non-ASCII data, after any transform, is written with
   leader/09=`a` and UTF-8 bytes that decode correctly downstream.
2. Pure-ASCII and already-UTF-8 records are byte-stable except the (correct)
   leader/09.
3. A regression test asserts leader/09 on output across the sandbox, convert,
   dedupe, and edit write paths.
4. Focused tests and the Docker test suite pass before completion.
