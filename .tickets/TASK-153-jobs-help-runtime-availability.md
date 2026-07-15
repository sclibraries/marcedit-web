# TASK-153 — Jobs help runtime availability

## Title

Fix the Jobs help dialog when the active runtime cannot read `docs/jobs.md`.

## Scope

- Reproduce the visible Jobs help error in the active runtime.
- Trace the source-relative help path through the active process, container,
  image, and deployment configuration.
- Correct the root cause with the smallest operational or code change.
- Preserve the canonical single-source help design from TASK-152.

## Success Criteria

- The root cause and affected runtime are identified with direct evidence.
- The active Jobs dialog renders the canonical guide.
- Automated coverage prevents the same runtime packaging/path failure where
  applicable.
- Relevant and complete tests pass with zero skipped tests.

## Status

Completed

## Root Cause

The active Docker container was created two weeks before TASK-152. Compose
bind-mounted the updated `marcedit_web/` source into that running container, so
the new dialog code executed immediately, but `docs/` is image content rather
than a bind mount. The old container therefore ran the new reader without its
new `/app/docs/jobs.md` dependency.

The current `marcedit-web:dev` image already contained the canonical guide.
Recreating the service from that verified image corrected the runtime mismatch;
no production-code change was required.

## Final Verification

- Before recreation, the active process resolved `/app/docs/jobs.md` and
  reported that it did not exist.
- After recreation, the same active-process check read the 4,673-character
  guide and confirmed its `# Jobs and Shared Cataloging` heading.
- The active container's dialog renderer opened `How jobs work`, emitted the
  canonical guide Markdown, and did not enter its error branch.
- The recreated `marcedit-web:dev` container is healthy.
- Focused Jobs and Docker packaging tests: 37 passed, zero skipped.
- Complete workspace-mounted Docker suite: 1,256 passed, zero skipped.
- Diagnostic review confirmed TASK-152's packaging and regression coverage are
  correct; the stale container was the only root cause, and no production-code
  change was needed.
