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

Status: In-Progress
