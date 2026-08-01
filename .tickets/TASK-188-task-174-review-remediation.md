Title: Remediate TASK-174 final review findings

Parent: TASK-174

Scope:
- Preserve the existing TASK-174 implementation in a checkpoint commit before
  remediation.
- Remove stale and contradictory ticket evidence and disclose the current
  image-only verification behavior.
- Fail closed on empty structural Find values and invalid raw-regex
  replacements.
- Correct RDA content/media/carrier classification, 260-to-264 indicators,
  abbreviation boundaries, relator preservation/deduplication, and unknown
  existing-field policies.
- Reject unproven caret-prefixed external SUBFIELD_EDIT syntax and route
  adapters through one registry.
- Restore literal-safe structural code generation and document deliberate
  field-order behavior.
- Address bounded performance and diagnostic-location findings without
  changing the canonical ordering contract.

Success Criteria:
- Every confirmed data-corruption or incorrect-RDA finding has a RED/GREEN
  regression test.
- Empty structural Find never reaches Python empty-pattern substitution.
- Retag and indicator operations that intentionally target all selected fields
  use an explicit match mode.
- RDA fields reflect explicit 007/Leader evidence and never default every
  material to computer/online.
- Unproven external caret syntax remains visible and blocking.
- Structural codegen rejects non-literal nested values before source emission.
- Ticket and image-only verification evidence is internally consistent.
- Focused and complete mounted-source Docker suites pass with every skip and
  image-only limitation reported.
- Independent review has no unresolved Critical or Important findings.

Status: Completed

Plan:
- `docs/superpowers/plans/2026-08-01-task-188-task-174-review-remediation.md`

Completion Evidence (2026-08-01):
- Checkpoint commit `c1dab43` preserved all prior implementation before the
  review corrections began.
- RED/GREEN focused suites cover empty structural matches, raw-regex capture
  validation, RDA carrier and policy correctness, caret-prefixed imports,
  fixed-position 008 conversion, nested codegen safety, inversion performance,
  record-zero diagnostics, and complete structural modal controls.
- Authoritative mounted-source Docker suite: `2065 passed, 5 skipped`. Four
  skips require a Docker CLI inside the test container; one is the unavailable
  private institutional corpus, with synthetic fixtures authoritative.
- Compose-like image suite: `2022 passed, 40 skipped, 8 failed`. The eight
  failures are disclosed repository-only product-identity checks whose inputs
  are intentionally absent from the runtime image; the generated reference is
  a loud skip there and passes in the authoritative mounted-source suite.
- Native compiler/reference freshness: `12 passed`; compiler manifest is
  unchanged. `git diff --check` passes.
- Post-remediation review found no unresolved Critical or Important finding;
  it also identified and corrected the previously hidden structural action and
  Find controls before closure.
