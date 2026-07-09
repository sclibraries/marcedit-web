Title: Release uploader widget memory after ingest (Home uploaders)

Scope:
- Streamlit's file_uploader keeps the full uploaded file in server RAM
  (MemoryUploadedFileManager) for as long as the file sits in the widget —
  typically the whole session. With the store already disk-backed
  (RecordStore), this widget copy is the largest persistent per-session
  memory consumer.
- Additionally, `00_Home.py` calls `_handle_uploaded_file(uploaded)` on
  every rerun while a file sits in either uploader, re-copying the bytes
  and re-writing the store to disk (and resetting issues_cache/editor
  state) on every widget interaction. (Verify during implementation.)
- Fix both Home uploaders (quick load `home_quick_load_upload`, job
  workspace `home_job_workspace_upload`) with the standard key-rotation
  pattern: after a successful ingest, persist the upload summary in
  session_state, bump a nonce embedded in the widget key, and rerun. The
  fresh widget is empty (RAM released); feedback renders from the stored
  summary.
- Rejected/failed uploads keep the file in the widget (no rotation) so the
  user sees the error next to their file.

Success Criteria:
- After a successful upload, the uploader widget no longer holds the file
  (nonce rotated) and the summary/next-actions UI still renders.
- A rerun after ingest does NOT re-invoke session.handle_upload for the
  same file (no re-parse churn).
- Upload-rejection paths (size cap, quota) still show their errors.
- Tests fail before the fix and pass after (Rule 9 / TDD).

Status: Completed (2026-07-09: TDD red→green; both Home uploaders rotate
keys after successful ingest; per-rerun re-ingest churn eliminated;
code-review findings fixed — zero-record uploads no longer rotate (error
renders), summaries are per-path and job-scoped; 958 tests pass)
