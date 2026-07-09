Title: Gate Home batch download behind an explicit prepare step

Scope:
- With a batch loaded, every Home rerun called session.current_raw_bytes()
  → RecordStore.to_mrc_bytes(), materializing the entire batch in RAM to
  feed st.download_button — re-creating the O(file) footprint on every
  script run and capping the benefit of TASK-131/132 (confirmed by the
  TASK-117 code review).
- Replace the always-rendered download button with a "Prepare download"
  button: bytes are built only on the run where it is clicked, the
  download button renders on that run, and Streamlit's media manager
  frees the payload as soon as a later run stops rendering the widget.
  Cost: another widget interaction before downloading makes the button
  disappear until Prepare is clicked again (documented in help text).

Success Criteria:
- Rendering Home with a loaded batch does NOT call current_raw_bytes.
- Clicking Prepare materializes once and renders the download button.
- Tests fail before / pass after.

Status: Completed (2026-07-09: TDD red→green; Home render with a loaded
batch no longer calls current_raw_bytes; Prepare-click materializes once)
