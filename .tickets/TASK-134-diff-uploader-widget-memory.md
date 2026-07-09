Title: Release Diff page uploader widget memory after ingest

Scope:
- The Diff page accepts up to 2 GB per file BY DESIGN (multi-GB vendor
  loads; quotas._DEFAULT_DIFF_BYTES). `_read_uploaded` already streams
  to disk via getbuffer() (no extra copy) and skips rewrites on rerun,
  and the page mmaps from disk — but the two multi-file uploader
  widgets (`diff_old_uploader`, `diff_new_uploader`) hold EVERY
  uploaded file in server RAM for the whole session. This is now the
  largest remaining per-session memory consumer (TASK-117 follow-up;
  Home equivalent fixed in TASK-131).
- Apply the TASK-131 key-rotation pattern, BUT: the current code
  overwrites `diff_old_buffers`/`diff_new_buffers` with whatever is in
  the widget, relying on the widget's accumulate-across-reruns
  behavior. With rotation the widget empties after ingest, so buffers
  must MERGE by filename instead of replace, and "Start over (clear
  Diff uploads)" remains the way to reset.

Success Criteria:
- After ingest, the uploader widgets are released (rotated) and the
  on-disk buffer list still shows all accepted files from multiple
  upload rounds.
- Re-uploading a same-named file replaces its entry (documented
  behavior), and Start over clears everything.
- Tests fail before / pass after.

Status: Todo (opened 2026-07-08, spun out of TASK-117/TASK-130 analysis)
