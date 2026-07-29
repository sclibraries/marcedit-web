Title: Finalize the Smith Metadata Studio display name

Parent: TASK-174

Scope:
- Set the centralized public product name to `Smith Metadata Studio`.
- Update user-facing documentation and identity tests to the approved name.
- Preserve the `marcedit-web` production folder, URL, distribution name,
  Python package, environment variables, Docker/service names, systemd entry
  points, startup commands, and technical routes.
- Rebuild and test the exact display-only rename in Docker before merge.

Success Criteria:
- Browser title, application heading/sidebar, and model-facing product identity
  use `Smith Metadata Studio`.
- `Record Editor` remains the user-facing editor name.
- No production/deployment identifier changes.
- Focused tests, the complete supported Docker suite, and Docker browser
  acceptance pass with every skip or evidence deviation reported.
- Code review has no unresolved Critical or Important findings.

Status: In-Progress

Design:
- `docs/superpowers/specs/2026-07-29-smith-metadata-studio-display-name-design.md`
