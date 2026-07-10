Task 4 Report: Complete Local FOLIO Standards Coverage

Ticket: .tickets/TASK-148-folio-rule-profiles.md
Design: docs/superpowers/specs/2026-07-10-folio-rule-profiles-design.md

Status: Completed

Scope Completed:
- Added local FOLIO rule coverage for configured 035 container code, multi-institution 506, configured 710 and 830 local access points, and detailed 949 required subfields.
- Extended FolioContext with container/collection/multi-institution runtime inputs needed by the new structured rules.
- Added constrained context-token resolution for field targets and add_context_field fixes.
- Kept fixes deterministic and structured; no arbitrary Python rule execution, no FOLIO API integration, and no silent export mutation.
- Mirrored the new default rules into the SQLite seed function using INSERT OR IGNORE semantics.
- Added the Task 4 focused standards and fix tests.

TDD Evidence:
- Initial host pytest run could not import marcedit_web because host Python setup is incomplete.
- Docker red run for the Task 4 focused tests failed as expected with missing rules/context:
  - 5 failed in 0.05s.
- After implementation, the same focused Docker command passed:
  - 5 passed in 0.03s.

Verification:
- Docker FOLIO test group:
  - docker compose run --rm marcedit-web pytest tests/test_folio_profiles.py tests/test_folio_profile_fixes.py tests/test_folio_profile_db.py -q
  - 22 passed in 0.27s.
- No-write syntax compile:
  - docker compose run --rm marcedit-web python -c "from pathlib import Path; [compile(Path(p).read_text(), p, 'exec') for p in ('marcedit_web/lib/folio_profiles.py', 'marcedit_web/lib/db.py')]"
  - passed.
- Whitespace check:
  - git diff --check
  - passed.

Self-Review Notes:
- The fixture already contains a 506 with blank indicators, so required_when_context_true now honors the configured field target and requires 506 1\ rather than accepting any 506 tag.
- 949 detailed messages include the actual missing subfields so catalogers can see what must be completed before FOLIO loading.
- Existing unrelated untracked file missing856.txt was not touched.

Concerns:
- docker compose compileall cannot be used against this container mount because source is read-only and bytecode writes fail. A no-write compile check was used instead.
