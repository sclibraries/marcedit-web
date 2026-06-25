# TASK-078a — Unify OCLC-035 extraction into one canonical helper

**Status:** Completed — implemented, reviewed (clean), merged to local main
**Worktree:** `.claude/worktrees/task-078a-oclc-035` (branch `worktree-task-078a-oclc-035`)
**Spec:** `docs/superpowers/specs/2026-06-18-oclc-035-unify-design.md`
**Parent:** TASK-078 (DRY consolidation) — sub-ticket 1 of 4 (078a–078d)
**Priority:** Tier 2 — Quality (divergent-bug risk; highest-correctness-first)
**Source:** Deep code audit 2026-06-17; scoped via brainstorm 2026-06-18

## Title

Replace the three divergent OCLC-035 extractors with one canonical helper,
deliberately resolving their 6-axis disagreement.

## Scope

- Add `normalize_oclc_035(value: str) -> str | None` to `transforms.py`:
  `lstrip` → require `(OCoLC)` prefix (else None) → strip prefix → `strip()`
  remainder → empty → None → return remainder verbatim.
- `reporting._oclc_from_035` delegates to the helper; returns the first
  non-None (display).
- `preflight._oclc_values` delegates to the helper; returns all non-None,
  keyed on the bare number. **Deliberate behavior change (user-approved
  2026-06-18):** bare numeric 035 $a (no `(OCoLC)`) is no longer treated as an
  OCLC number, and dedup keys drop the prefix — aligning preflight with diff.
- `marc_diff` OCOLC extraction already produces the canonical result via its
  generic byte-level FieldSpec; do not refactor the generic mechanism — instead
  pin equivalence with a test asserting its OCLC output matches
  `normalize_oclc_035` across the divergence table.

## Non-Goals

- No `ocm`/`ocn`/`on` + leading-zero normalization (keep distinct, as today).
- "First vs all 035s" stays a per-caller choice, not baked into the helper.

## Success Criteria

1. `_oclc_values` and `_oclc_from_035` have exactly one shared semantic source
   (`normalize_oclc_035`); behavior matches the canonical rules.
2. A preflight test proves a bare-number 035 is no longer flagged as an OCLC
   duplicate, while two `(OCoLC)`-prefixed records still are (pins the resolved
   divergence).
3. A diff↔helper equivalence test prevents silent re-divergence.
4. Focused tests and the Docker test suite pass before completion.
