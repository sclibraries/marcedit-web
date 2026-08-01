Title: Replace opaque RDAHELPER imports with explicit deterministic operations

Parent: TASK-174

Scope:
- Define visible, independently selectable RDA operations rather than emulate
  an opaque external RDAHELPER instruction.
- Evaluate abbreviation expansion, 260/264 handling, 336, 337/338, GMD,
  relators, and configured templates as separate behaviors.
- Document confirmed behavior, strong inference, and unknown behavior
  separately.
- Use open MARC21 and RDA-facing rules and local policy decisions; do not copy
  or redistribute proprietary implementation artifacts.
- Keep processing deterministic and require cataloger review of imported
  external instructions.

Success Criteria:
- Each supported RDA transformation has an explicit name, inputs, preview,
  documentation, and intent-focused tests.
- Unknown external RDAHELPER settings remain visible and blocking rather than
  receiving guessed defaults.
- The application makes no claim of universal external-tool compatibility.
- Focused and complete supported Docker suites pass with every skip reported.
- Independent review has no unresolved Critical or Important findings.

Status: Completed

Review remediation: TASK-188

Plan: `docs/superpowers/plans/2026-08-01-task-181-explicit-rda-operations.md`

Design:
- `docs/superpowers/specs/2026-07-31-task-181-explicit-rda-operations-design.md`

Implementation checkpoint (2026-08-01):
- Added explicit deterministic RDA operations, visible Smith profile expansion,
  modal preview/override controls, operation-reference entries, and ambiguity
  reporting without guessed material mappings.
- Verified by `tests/test_rda_operations.py` and the complete mounted-source
  Docker suite (`2042 passed, 5 skipped`).

TASK-188 review remediation (2026-08-01):
- Leader/06 content classification now combines explicit 007 carrier evidence;
  print text receives unmediated/volume while `007=cr` receives
  computer/online resource, and unsupported carrier evidence fails before
  mutation.
- 260 promotion sets 264 indicator 2 to publication (`1`), reviewed
  abbreviations match complete tokens, `$4` relator codes are retained while a
  missing `$e` is added once, and unknown existing-field policies fail closed.
