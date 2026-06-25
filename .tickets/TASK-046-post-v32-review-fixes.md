# TASK-046 — Post-v3.2 review fixes

**Status:** Completed
**Stage:** v3.2 cleanup.

## Title

Seven findings from the v3.2 review:

1. **Medium** — Quick find/replace preview has no match cap; a
   broad query on a 100K-record batch runs the sandbox over the
   whole matched subset and can take minutes.
2. **Medium** — Quick find/replace Apply only re-fingerprints
   matched records. If the cataloger swaps the loaded batch between
   Preview and Apply, the fingerprint check could pass by accident
   on identical records in the new batch.
3. **Medium** — Find page caches results by query text only;
   re-running the cached query after a new upload renders stale
   results.
4. **Low/Medium** — Search docs advertise ``008/35-37:eng`` byte
   ranges but the parser only accepts single integers.
5. **Medium** — Dedupe strategy apply does ``bytes(mm)`` once,
   doubling memory transiently. Documented in-code, acceptable for
   typical batches; add a clearer in-code TODO + a follow-up
   ticket reminder.
6. **Policy gap** — Dedupe strategy / manual override / deletes
   export are not audited. Deletes export is action-shaped; emit
   an audit event for it.
7. **Low** — README still describes ``Home.py`` and ``pages/``;
   navigation migrated to ``App.py`` + ``views/`` in TASK-045.

## Scope

- **`lib/batch_replace.py`**:
  * Add `MAX_PREVIEW_MATCHES = 500` cap. When ``matched_indices``
    exceeds the cap, preview runs the sandbox over the first 500
    only; Apply still operates on the full set. Preview carries a
    ``preview_cap_triggered`` flag the UI surfaces.
  * Add ``batch_identity`` field to ``BatchReplacePreview``:
    ``(filename, record_count)`` snapshot at preview time. Apply
    rejects if the current batch identity differs.
- **`render/find.py`**:
  * Results dict gains a ``batch_identity`` field; renderer
    clears stale results when the active batch changes.
- **`lib/search.py`**:
  * Parser accepts ``tag/N-M:value`` byte-range form. ``SearchQuery``
    grows ``byte_end: Optional[int]`` (None = single-byte at
    ``byte_position``). ``_byte_position_matches`` becomes range-
    aware (the haystack is ``data[byte_position:byte_end + 1]``).
- **`render/dedupe.py`**:
  * Emit a new ``dedupe-deletes-issued`` audit event when the
    deletes ``.mrc`` is built (user, filename, strategy, params,
    groups touched, deletes count). Adds the new event kind to
    ``audit.py`` docstring + ``docs/deployment.md``.
  * `bytes(mm)` copy already commented; add a TODO pointing at
    the follow-up direction (per-record slicing avoids the copy).
- **README.md**: refresh the layout section to describe
  ``App.py`` + ``views/`` and the four navigation sections.
- **Tests**:
  * ``test_batch_replace.py`` — preview cap triggers correctly;
    Apply rejects on batch-identity drift.
  * ``test_search.py`` — byte-range parser + matcher.

## Out of scope

- A streaming Dedupe path that avoids the ``bytes(mm)`` copy.
  Worth tracking but the cost is bounded for typical batches and
  the refactor (per-record slicing across the dedupe-strategy
  helpers) is its own piece of work.
- Auditing every keeper override or strategy application — only
  the deletes export is action-shaped enough to warrant an audit
  event. Strategy / override events would be noise.

## Success Criteria

1. Quick find/replace preview on a query matching 5,000 records
   surfaces a "previewing first 500 of 5,000" notice and the
   sandbox runs against 500 records.
2. Loading a new file between Preview and Apply blocks Apply with
   a clear "batch changed" error.
3. Find page results render once; after a new upload, the cached
   results are dropped and a fresh search is required.
4. ``008/35-37:eng`` parses and matches.
5. Dedupe deletes export adds a ``dedupe-deletes-issued`` audit
   row.
6. README accurately describes the layout.
7. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
```
