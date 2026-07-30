# TASK-179 Cataloger Browser Smoke Evidence

- Candidate commit: `2e887ee`
- Docker image digest:
  `sha256:075f8a4330d5cb555077391ecfd20f2f5565cafc4c0050e068d2d82e6afd518b`
- Browser URL: `http://localhost:8501`
- Authentication: the existing local OAuth configuration was mounted
  read-only, and `smith.edu` was added only to the isolated TASK-179 test
  database. No production or main-worktree authentication state changed.
- Synthetic fixture: a non-production MARC record containing 001 and 003.
- Add Field rows: accepted. The cataloger could enter representative 852 and
  877 subfields as ordered code/value rows without JSON.
- 035 Build Field: accepted with indicator 1 `9`, blank indicator 2, literal
  parentheses, and structured 003/001 source segments.
- 876 Build Field: accepted as structured subfields equivalent to
  `=876  \\$aB({003}){001}-SC$lInternet`.
- Save/reopen: accepted; structured values and order remained visible through
  the form workflow.
- Missing-control behavior: the form exposed the explicit skip/error policies.
- Ambiguous import refusal: unresolved external Build Field syntax remained
  visible and required recreation through structured controls.
- Existing unresolved task edit/run boundary: unresolved Add/Build
  instructions remain visible but are refused at submission.
- AI/network boundary: no AI prompt or AI-generated operation appeared. The
  existing AI implementation remains frozen and deferred.
- Accessibility snapshot: not captured. Neither approved browser automation
  client was available in this session; the cataloger performed the
  walkthrough directly.
- Screenshot: not captured for the same reason.
- Cataloger disposition: accepted on 2026-07-30 with “This all looks good.”
- Follow-up observation: the existing Subfield Replace form does not explain
  whether regex replacement changes only matched text or the complete
  subfield. This is outside TASK-179 and is routed to TASK-180, whose design
  requires explicit replacement-scope and preservation controls.
- Documentation follow-up: TASK-183 will provide cataloger-facing explanations,
  examples, and usage guidance for every deterministic task operation.
- Deviations: automated accessibility and screenshot evidence were
  unavailable and are disclosed above. Manual cataloger acceptance completed.
