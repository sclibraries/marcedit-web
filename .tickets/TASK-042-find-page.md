# TASK-042 — Find page (cataloger-friendly match set view)

**Status:** Completed
**Stage:** v3.2 cataloger workbench (after TASK-036).

## Title

The View page already has a search bar but it shows matches one
record at a time via Prev/Next. For "find all records where 035
starts with EDZ" the cataloger wants the full match set as a
list — to inspect, export, or act on as a group. Add a top-level
**Find** page that surfaces matches as a table and offers
"act on the set" actions.

## Scope

- **`lib/search.py`** gets four new operators:
  * ``^prefix`` — value starts with prefix (literal).
  * ``suffix$`` — value ends with suffix (literal). The trailing
    ``$`` is the sigil; ``$`` inside the value (legitimate in
    subfield delimiter syntax) is unaffected because the sigil
    is only recognized at the **end** of the value.
  * ``~pattern`` — regex match (case-insensitive unless the user
    flips the global case-sensitive toggle).
  * ``<query1> AND <query2>`` — compound AND. Each clause is a
    standalone SearchQuery; record matches iff every clause
    matches.
- The existing default-contains behavior is preserved. ``parse_query``
  for a single clause returns a ``SearchQuery``; new
  ``parse_compound_query`` returns ``list[SearchQuery]`` for callers
  that handle the AND case.
- ``SearchQuery`` grows a ``mode`` field:
  ``"contains" | "starts" | "ends" | "regex"`` (default
  ``"contains"``). ``_record_matches`` switches on mode.
- **New page** ``marcedit_web/pages/7_Find.py``:
  * Query input + submit.
  * In-page help block enumerating operators with examples,
    explicitly calling out that ``~`` is for catalogers comfortable
    with regex syntax.
  * Bad-regex / malformed-compound errors surface inline.
  * **Match table** (paginated, 25/page): record #, 001 identifier,
    245$a snippet, match snippet (the value that triggered the
    match, truncated to ~80 chars).
  * **Counts header**: "X matches of Y total records".
  * **Action buttons** below the table:
    * "Open first match in View" — jumps to View, pre-sets
      ``view_index`` to the first match's 1-based index.
    * "Export matches as .mrc" — writes the matched subset via
      ``store.write_mrc_to`` into a temp file, offers a download.
    * "Send to Quick find/replace" — stashes matched indices in
      session_state and points the cataloger at the Tasks page's
      wizard (the wizard's match-scope will land in TASK-036.1
      follow-up; for v1, just opens the wizard with no scope
      restriction).
- **New render module** ``marcedit_web/render/find.py`` keeps the
  page logic testable + reusable.
- **Tests** ``tests/test_search.py``:
  * ``parse_query`` recognises ``^X`` (starts) and ``X$`` (ends).
  * ``parse_query`` recognises ``~pattern`` (regex) and catches
    bad-regex with a fallback to contains.
  * ``parse_compound_query`` splits on ``AND`` (case-insensitive,
    word-boundary).
  * ``matching_records_compound`` returns only indices that
    satisfy every clause.
  * Each mode produces the expected match set against the
    fixture's records.

## Out of scope

- **OR / NOT queries.** Add when catalogers ask. Most batch
  workflows need AND.
- **Field-presence queries** ("records that have an 035"). Worth
  doing later; the syntax would be e.g. ``has:035``.
- **Date-range queries on 008.** Specialized aggregate that
  belongs on the Reports page expansion or its own predicate.
- **Save / replay searches across sessions.** Per-session
  recent-queries list could land in a follow-up.
- **Match-scope passthrough to Find/Replace.** The wizard
  currently runs on the full batch; honoring a passed-in match
  set is a TASK-036 follow-up. The "Send to Quick find/replace"
  button just navigates for v1.

## Success Criteria

1. With sample.mrc loaded, Find page query ``245$a:Pistoletto``
   returns one match in the table.
2. Query ``035$a:^EDZ`` (or whatever prefix exists in fixture)
   surfaces only records whose 035 $a starts with that prefix —
   not records where EDZ appears mid-string.
3. Bad regex (``~(unbalanced``) shows a clear inline error and
   doesn't crash the page.
4. Compound query ``245$a:Pistoletto AND 008/35-37:eng`` returns
   the intersection of the two clauses.
5. "Export matches" produces a valid `.mrc` containing only the
   matched records (verified via ``pymarc.MARCReader``).
6. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_search.py
docker compose run --rm marcedit-web pytest -q
```
