# TASK-003 — Session state + identity shim

**Status:** Completed
**Stage:** 3 (per `/Users/roconnell/.claude/plans/the-goal-of-this-sequential-sifakis.md`)

## Title

Wire up the per-session state shape, the file-upload widget, and the
Shibboleth-ready identity shim. After this stage, the Home page accepts
a `.mrc` upload, parses it into `st.session_state.records`, and surfaces
the active user (read from `REMOTE_USER`/`eppn` headers, or `anonymous`
in dev) so every later page has data to work with.

## Scope

- `marcedit_web/lib/identity.py` — `current_user(headers=None) -> str`.
  Reads `st.context.headers["REMOTE_USER"]` or `["eppn"]`, falls back
  to `"anonymous"`. Accepts an optional `headers` arg so tests don't
  need a Streamlit runtime context. Never logs the value.
- `marcedit_web/lib/session.py` — session-state initialization, the
  pure `parse_uploaded_bytes(data) -> (records, malformed_count)`
  helper, and the Streamlit-flavored `handle_upload(uploaded_file)` +
  `download_bytes()` helpers. State keys per the plan: `user`,
  `filename`, `raw_bytes`, `records`, `malformed_count`,
  `issues_cache`, `editor_text`, `editor_dirty`,
  `tasks_palette_state`, `diff_*` (namespace reserved).
- `marcedit_web/Home.py` — replaces the Stage 1 placeholder. Wires the
  uploader, displays loaded-file metadata, surfaces the active user in
  the sidebar.
- `tests/test_identity.py`, `tests/test_session.py` — cover the pure
  surface (parsing + identity).

## Out of scope for this ticket

- The Validate / View / Report / Tasks / MarcEditor / Diff pages.
  Those land in their own stages.
- Loading `data/marc-rules.txt` — Stage 4.
- Persisting state across sessions (explicitly never; session-only
  was confirmed in the plan).

## Success Criteria

1. `current_user()` returns `"anonymous"` when no headers are present;
   returns the `REMOTE_USER` header when set; falls back to `eppn`
   when `REMOTE_USER` is empty.
2. Uploading a `.mrc` via the Home page populates `session_state.records`,
   `session_state.raw_bytes`, `session_state.filename`, and
   `session_state.malformed_count`.
3. The Home page shows record count, filename, and active user after
   upload.
4. A "Download current batch" button on the Home page returns the
   current `session_state.raw_bytes` (placeholder; later stages will
   re-encode edited records).
5. `docker compose run --rm marcedit-web pytest -q` stays green.
6. `docker compose up -d` + `/_stcore/health` stays ok, and a Playwright
   smoke test confirms the upload widget renders.

## Verification commands

```sh
docker compose run --rm -e PYTHONPATH=/app marcedit-web pytest -q
docker compose up -d --build
curl -fsS http://localhost:8501/_stcore/health
# Then drive the upload via Playwright (or manually open the URL).
docker compose down
```

## Verification result (2026-05-21)

- New modules:
  - `marcedit_web/lib/identity.py` — `current_user(headers=None)`
    reads `REMOTE_USER` then `eppn`, falls back to `"anonymous"`. Tests
    cover the precedence order, whitespace trimming, empty-header
    fall-back, and the no-PII-logging contract.
  - `marcedit_web/lib/session.py` — `STATE_DEFAULTS`, `init()`,
    `parse_uploaded_bytes()` (pure), `handle_upload()`, plus the
    session readers (`has_upload`, `current_filename`, `current_records`,
    `current_raw_bytes`). The Streamlit `st.session_state` and the
    `st.file_uploader` widget are exercised only via Playwright.
- `Dockerfile` adds `PYTHONPATH=/app` so the Streamlit entry script can
  resolve `from marcedit_web.lib import session` (the default sys.path
  Streamlit injects is the entry-script directory, not the project root).
- `Home.py` rewritten: handles the upload FIRST, then renders the
  sidebar (so sidebar shows fresh state on the same run), then the
  inline status, the loaded-batch metrics, and a download button that
  echoes back the original upload bytes (Stage 3 placeholder — Stage 10
  will swap in re-encoded edited records).
- Pytest: 99 passed, 0 failed (15 new tests added: 9 identity + 6
  session).
- Playwright smoke: started the stack, navigated to /, uploaded
  `tests/fixtures/sample.mrc` (26.6 KB, 7 records), confirmed:
  * sidebar updates to "Loaded: sample.mrc / 7 records" on the same
    run as the upload;
  * "Signed in as anonymous" surfaces in the sidebar (no headers in
    dev);
  * main pane shows success alert, three metrics (Filename / Records /
    Malformed), and the Download button;
  * `docker compose down` clean.

All six success criteria satisfied.
