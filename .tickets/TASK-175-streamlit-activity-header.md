Title: Restore Streamlit activity feedback without developer controls

Scope:
- Restore the Streamlit framework header/status area so catalogers can see the
  running indicator during otherwise quiet reruns and operations.
- Verify the configuration against the project's pinned Streamlit version in
  Docker.
- Preserve current Account and operation-notification controls and keep
  developer and deployment controls unavailable.
- Keep this work independent of TASK-174's native task migration and
  TASK-173's infrastructure release.

Success Criteria:
- A deliberately slow rerun visibly shows the Streamlit running indicator.
- Developer and deployment controls remain unavailable to catalogers.
- Account and operation-notification controls do not overlap the header.
- Public and private modes behave consistently.
- Existing in-page progress remains available.
- If configuration alone is insufficient, styling hides only proven unwanted
  controls rather than the complete header.
- Applicable tests pass with every skip reported and code review has no
  unresolved Critical or Important findings.

Status: Todo

Context:
- `.streamlit/config.toml` currently sets `[client] toolbarMode = "minimal"`.
- The first configuration to test is `viewer`, which Streamlit documents as
  hiding developer options from viewers.
- Reference: https://docs.streamlit.io/develop/concepts/architecture/app-chrome

Design:
- `docs/superpowers/specs/2026-07-31-task-175-streamlit-activity-header-design.md`
