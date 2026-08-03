Title: Preserve the partner-library external task corpus

Parent: TASK-174

Scope:
- Preserve the public UMass/Five Colleges FOLIO MarcEdit task collection as a
  segregated third-party compatibility corpus.
- Copy upstream task archives verbatim and record their repository URL, exact
  source commit, GPL-3.0 license, and the user's confirmation of partner-library
  permission on 2026-08-03.
- Keep the corpus distinct from Smith-authored and synthetic test fixtures.
- Verify that the existing external-task audit reads every archive and gives
  every unresolved instruction a concrete next action.
- Do not change importer behavior or claim new external semantics in this
  ticket.

Success Criteria:
- All 49 upstream `.task` archives are present and byte-identical to the
  recorded upstream commit.
- The upstream license and a provenance notice travel with the corpus.
- The audit reports 49 documents, classifies every instruction, and reports no
  unclassified item or unresolved item without a next action.
- Focused corpus-audit tests pass with no skips.
- Review confirms that no runtime data, Smith institutional task, or importer
  implementation change is included.

Status: Completed

Completion evidence (2026-08-03):
- Preserved 49 byte-identical upstream archives from commit
  `d07377a58cba9d0936a63863c9d428498609d5e5` with the GPL-3.0 license,
  provenance notice, and a checked-in SHA-256 manifest.
- The committed corpus audit reports 49 documents and 1,239 instructions:
  693 converted and 546 actionable blockers, with zero unclassified items and
  zero blockers without a cataloger next action.
- TDD regression tests cover complete filename/hash equality, corpus counts,
  classification completeness, and visible cataloger-action CLI output.
- Supported Python 3.9 Docker verification:
  `147 passed in 0.60s`, with zero failures and zero skips.
- Independent review and re-review reported no remaining Critical, Important,
  or Minor findings.
- No importer implementation, application runtime, production data, Smith
  institutional fixture, service, or deployment behavior changed.
