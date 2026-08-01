# TASK-175 browser smoke evidence

Date: 2026-08-01

Environment: isolated Docker image `marcedit-web:dev`, public mode on
`http://127.0.0.1:8502`, with the synthetic `tests/fixtures/sample.mrc`
fixture.

Checks performed:

- The page rendered the Smith Metadata Studio app header and toolbar.
- The toolbar contained the framework menu only; no Deploy, developer, or
  deployment controls were present.
- The Account/header control remained present at the top right.
- Re-uploading the fixture triggered a rerun. A Playwright DOM poll observed
  three running/status elements during the rerun, then they disappeared when
  the rerun completed. This confirms the native activity indicator is
  available while idle pages remain visually quiet.
- The fixture loaded successfully with 7 records and 0 malformed records.

The private-mode page was also opened and correctly stopped at its existing
sign-in gate; the same native header and toolbar were present there. No
application service or ITS-managed configuration was changed.
