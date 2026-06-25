# TASK-044 — Dedupe regex strategy: error visibility + match counts

**Status:** Completed
**Stage:** v3.2 follow-up to TASK-043.

## Title

Cataloger reported: typing the pattern ``^(SCSK`` into the
``FIELD_MATCHES_REGEX`` strategy and clicking Apply produced a
``"strategy applied"`` success message but the keepers came out as
first-occurrence. The pattern has an unbalanced ``(`` — Python's
regex compiler raises ``re.error`` — and the lib silently fell back
to first-occurrence on every group. The cataloger saw no error and
no indication the rule hadn't matched.

## Scope

* **`lib/dedupe_strategy.py`**:
  * New ``validate_params(strategy, params) -> str | None`` —
    catches missing tag / missing pattern / bad regex compile at
    the lib layer so callers don't depend on the silent-fallback
    behavior. The error message points at how to escape literal
    parens (``\\(`` and ``\\)``) since that's the most common
    cataloger trip-wire.
  * ``pick_keeper`` now returns ``(offset, matched_strategy)`` —
    the flag tells callers whether the strategy criterion actually
    selected a record vs falling back to first-occurrence.
  * ``apply_strategy_to_groups`` returns
    ``({group: offset}, matched_count)``.
* **`render/dedupe.py`** strategy picker:
  * Calls ``validate_params`` on every render; shows the error
    inline; disables the **Apply strategy** button until the
    params validate.
  * After Apply, surfaces match counts for ``FIELD_MATCHES_REGEX``:
    * 0 matches → ``st.warning`` pointing at the paren-escape rule.
    * Partial matches → ``st.success`` showing matched + fallback
      counts ("247 matched the regex; 3,753 fell back to first").
    * Full matches → plain "applied to N groups".
* **Tests** ``tests/test_dedupe_strategy.py`` (7 new):
  * ``validate_params`` for each strategy: required fields,
    bad-regex rejection (with the user's actual ``^(SCSK``
    pattern), escaped-paren acceptance.
  * ``apply_strategy_to_groups`` returns the correct
    ``matched_count`` when some groups don't have a matching
    member.

## Out of scope

- **Defusedxml-style stronger regex validation.** Python's
  ``re.compile`` is the canonical authority here; pre-validation
  is purely a "fail loudly instead of silently."
- **Per-group "this group fell back" indicator in the table.**
  The aggregate match-count message is enough for v1; per-row
  drill-down can come if it's asked for.

## Success Criteria

1. Typing ``^(SCSK`` and clicking Apply now blocks with a clear
   regex error message AND a hint to escape the paren.
2. With the corrected pattern ``^\\(SCSK`` the strategy picks the
   right record AND the success message reports the match count.
3. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_dedupe_strategy.py
docker compose run --rm marcedit-web pytest -q
```
