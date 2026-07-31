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

Status: Todo

Design:
- `docs/superpowers/specs/2026-07-31-task-181-explicit-rda-operations-design.md`
