# TASK-014 — Advanced search in View

**Status:** Completed
**Stage:** 14 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md` v2)

## Title

Add a search bar to the View tab that supports a small,
tag/subfield-aware query language. Closes user-surfaced problem #4
("In view we need more advanced search options looking for specific
words or subfields").

## Why

v1's View page can navigate record-by-record or filter the
*displayed* tags within a record, but it cannot find "records where
245 $a contains *Pistoletto*". For a 100K-record batch that's the
difference between usable and not.

## Scope

- New file: `marcedit_web/lib/search.py`:
  * `SearchQuery` dataclass (`text`, `tag`, `subfield`,
    `byte_position`, `case_sensitive`).
  * `parse_query(s) -> SearchQuery` — supports:
    - `foo` → plain text, search any field
    - `245:foo` → tag-scoped
    - `245$a:foo` → tag + subfield
    - `008/28:i` → control field at byte position
    - `245$a:"exact phrase"` → quoted phrases
  * `matching_records(store, query) -> Iterator[int]` — streams
    0-based record indices.

- Wire a search bar into `render/view.py` (and therefore both the
  Workspace's View tab and the deep-link `/View` page). When the
  query is non-empty:
  * Compute matching indices once per render.
  * If empty, show a "No matches" message and keep the navigator on
    the current record.
  * If non-empty, Prev/Next jump between matches; banner shows
    "Match X of N matches — Record #Y of TOTAL".

- Tests (`tests/test_search.py`):
  * Parser: each documented form (plain / tag / tag-sub / tag-byte
    / quoted) plus malformed input → text fallback.
  * Match: against `sample.mrc` —
    - `Pistoletto` → matches record 1.
    - `245$a:Pistoletto` → matches record 1.
    - `245$a:absurdo-not-in-fixture` → no matches.
    - `008/28: ` (space) → all 7 records (every record has blank
      byte 28 in the fixture).
    - `008/28:i` → 0 records (none are international intergov).

## Out of scope

- Multi-condition queries (AND/OR/NOT) — single condition for v2.
- Regex search — substring only.
- Streaming pagination of large match sets — Stage 16.

## Success Criteria

1. `parse_query` round-trips every documented form to the right
   `SearchQuery` fields.
2. `matching_records` returns the expected indices for each test
   case against `sample.mrc`.
3. View tab renders a search input above the navigator; entering
   `245$a:Pistoletto` filters to record 1.
4. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
docker compose up -d
# Playwright: Home → upload sample.mrc → View → enter
# 245$a:Pistoletto in the search bar → confirm "Match 1 of 1
# matches" + record 1 rendered. Clear → all 7 records back.
docker compose down
```

## Verification result (2026-05-24)

- `marcedit_web/lib/search.py` added (220 LOC including helpers).
  Procedural parser (regex-free); handles `foo`, `245:foo`,
  `245$a:foo`, `008/28:i`, `LDR/6:a`, quoted phrases, and any
  malformed input falls back to plain-text search. Match engine
  streams 0-based record indices.
- View tab + Workspace's View tab now show a search input above
  the navigator. When a search is active, Prev/Next constrain
  to matches and the banner reads "Match X of N (record #Y of
  TOTAL)".
- Tests: 23 new (12 parser + 11 match) under `tests/test_search.py`.
  Total **219 passed in 0.40s**.
- Playwright smoke: Home → upload `sample.mrc` → View → typed
  `245$a:Pistoletto` → page updated to "`1` match(es) for
  `245$a:Pistoletto`. Prev / Next jump between matches" +
  "**Match 1 of 1** (record #1 of 7) — `1587455634` — Michelangelo
  Pistoletto". Prev/Next disabled (single match); the record body
  still renders cleanly below.

All four success criteria satisfied.
