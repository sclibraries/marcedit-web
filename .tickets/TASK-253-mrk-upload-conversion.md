Title: Accept MRK uploads and fix MARC Tools binary downloads

Status: In-Progress

Scope:
- Fix undefined stamp in MARC Tools downloads.
- Accept MRK through Quick Load and job attachments using existing parser and binary persistence.
- Convert and verify the supplied artemis2.mrk; preserve the source.
- Target production Streamlit baseline b227046 in this isolated worktree.

Success Criteria:
- Test-first regressions cover downloads, MRK loading/restoration, malformed input, and quotas.
- Existing MRC behavior passes relevant tests and code review.
- Supplied file converts with verified records/fields; deployment status is explicit.

Implementation and review — 2026-09-21:
- Confirmed production and origin/main at clean b227046; active unit is
  marcedit-web.service, running as marcedit. No infrastructure or schema changes.
- Reproduced 12 upload/download failures, including the exact undefined-stamp
  traceback. Two streaming-conversion tests also failed before implementation.
- Added record-at-a-time UTF-8/BOM MRK conversion with staged output, explicit
  parser errors, source/output byte limits, and existing binary persistence.
- Quick Load and shared job attachment pickers accept MRK; stored files and
  downloads use .mrc names. Binary upload streaming remains unchanged.
- Review found missing record separators could silently merge records in the
  existing parser. A regression failed first; upload conversion now rejects this
  case with its source line. Interactive converter behavior is otherwise retained.
- Focused Python 3.9.25 / Streamlit 1.50 suite: 229 passed, no skips. Covers parser,
  conversion, upload, refresh, job-file workflows, and quotas. Full repository suite
  and a live authenticated browser upload have not been run.
- Source review checked all modified call paths, staged-file lifetime, state
  preservation on errors, UTF-8 fields, filename/storage size consistency, and
  unchanged MRC behavior. git diff --check passes.
- Supplied artemis2.mrk converted to artemis2.mrc (one record, 3,555 bytes), with
  every parsed field equal after binary reread. Both files remain outside Git.
- Production deployment pending. Rollback source is b227046; no data migration.
