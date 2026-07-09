Title: Stream uploads to disk instead of materializing bytes

Scope:
- `session.handle_upload` calls `uploaded_file.getvalue()`, materializing
  a second full copy of the upload in RAM (on top of the widget's copy)
  before `RecordStore.from_bytes` writes it to disk. Peak RAM per upload
  is ~2× file size.
- Add `RecordStore.from_file(fileobj, ...)` that chunk-copies the file
  object to the backing path (shutil.copyfileobj) and then builds the
  offsets index from the on-disk bytes, mirroring `from_bytes` semantics
  (filename, malformed count, tmp_dir handling).
- Switch `handle_upload` to `from_file`; derive `size` from the uploader's
  size attribute / on-disk size rather than len(raw).

Success Criteria:
- No full-file `getvalue()` in the ingest path; upload bytes reach disk
  via chunked copy.
- from_file produces a store identical to from_bytes for the same input
  (same count, malformed, iteration, to_mrc_bytes round-trip) — covered
  by tests that fail before and pass after.
- Existing upload/quota audit behavior unchanged (size still recorded).

Status: Completed (2026-07-09: RecordStore.from_file streams via 1 MB
chunks + mmap-indexed; handle_upload no longer materializes uploads;
enforced by tests whose upload fakes raise on whole-body reads;
code-review pass clean for this path; 958 tests pass)
