# TASK-078 — Consolidate duplicated MARC primitives (DRY)

**Status:** Decomposed (2026-06-18) — split into sub-tickets after investigation showed 8 independent consolidations of varying risk:
- **078a** — OCLC-035 unify (behavior-changing; in progress)
- **078b** — single identity-read accessor (pairs with TASK-073)
- **078c** — mechanical/identical batch (`_is_control_tag`, `_record_issue`, 9× `_stamped_filename` → 1 helper, session-state key constants)
- **078d** — divergent-semantics batch (record-identifier, `control_value` strip, subfield-replace codegen, MRK subfield parsing)

**Priority:** Tier 2 — Quality (divergent-bug risk)
**Source:** Deep code audit 2026-06-17 — quality findings (43 confirmed)

## Title

Collapse the MARC primitives that are reimplemented across modules into single
owners, removing the "fix one copy, miss the other" hazard.

## Scope (highest correctness risk first)

- One OCLC-035 extraction helper, replacing the three divergent definitions in
  `preflight._oclc_values`, `reporting._oclc_from_035`, and `marc_diff`
  OCOLC_SPEC. (MEDIUM — they disagree on what counts as an OCLC number.)
- Route all user-identity reads through `identity.current_user()` (10 inline
  sites in `render/tasks.py`, `marc_tools.py`, `dedupe.py`) — pairs with
  TASK-073 so the attestation check is single-point.
- One `subfield-replace` codegen path (`task_builder._render_one` vs
  `marcedit_import._emit_subfield_edit`).
- One record-identifier helper (currently triplicated with divergent
  semantics); one `_is_control_tag` / `_record_issue` / `control_value`; one
  indicator-normalization helper; one `_stamped_filename` (≈9 copies); shared
  session-state key constants (`view_index`, `issues_cache`).
- Unify MRK subfield parsing between `mrk_parser` and `marcedit_import`.

## Success Criteria

1. Each listed duplicate has exactly one definition; callers updated; behavior
   preserved (or a semantic divergence resolved deliberately and noted).
2. No abstraction beyond what removes the duplication (surgical, per CLAUDE.md
   Rules 2–3).
3. Focused tests and the Docker test suite pass; add a test where consolidation
   resolves a real divergence (e.g. OCLC-035 semantics).
