Title: Preserve canonical MARC field order in View

Scope:
- Trace how records and fields reach the View page and determine whether View
  reorders fields or exposes an upstream mutation.
- Preserve actual source order while validating it against the application's
  ascending-tag convention, including the expected placement of tag 035.
- Warn without sorting or mutating the record.

Success Criteria:
- A regression fixture containing leader, control fields, repeated fields,
  035, and surrounding data fields renders in its original order.
- View reports a bounded diagnostic when an adjacent tag inversion occurs,
  such as 040 followed by 035.
- Repeated tags do not produce a warning and valid order remains silent.
- Applicable focused tests and review pass without unresolved Critical or
  Important findings.

Status: Completed

Evidence:
- Helper RED failed on the four missing `field_order_inversions` calls with
  the expected `AttributeError` (`4 failed, 20 passed`). Helper GREEN:
  `24 passed, 0 skipped, 0 warnings`.
- Initial View contract RED failed because View did not call the inversion
  helper (`1 failed, 5 passed`). View GREEN across the TASK-169 focused suite:
  `39 passed, 0 skipped, 0 warnings`.
- Behavioral mutation RED temporarily removed the order-warning block without
  committing the mutation. The ascending-order case passed while the inverted
  and over-20-inversion cases failed on zero captured warnings
  (`2 failed, 1 passed`). After restoring the production block, behavioral
  GREEN was `3 passed, 0 skipped, 0 warnings`.
- Coverage proves the helper does not mutate the record by comparing exact
  `record.as_marc()` bytes before and after diagnosis; human rendering retains
  deliberate `001`, `040`, `035`, `245` source order; equal/repeated tags and
  ascending order remain silent; and diagnostics stop at 20 transitions.
- Behavioral View coverage proves an inverted record emits exactly one warning
  before human rendering, includes the source-order wording and
  `040 before 035`, while an ascending record emits no order warning.
- Final authoritative network-disabled Python 3.9 Docker suite:
  `42 passed, 0 failed, 0 skipped, 0 warnings`.
- Static checks passed: `python3 -m py_compile` for `viewer.py`, `view.py`, and
  `test_view_render.py`; `git diff --check` clean. Static source inspection
  confirmed no sorting or `record.fields` assignment in the scoped path.
- Commits: `cd5b90e` (`feat: detect MARC field order inversions`), `21e9264`
  (`feat: warn on MARC field order inversions`), and `e9e854d`
  (`test: cover MARC field order warnings`).
- Final independent re-review: Approved and spec compliant, with no Critical,
  Important, or Minor findings.
