# TASK-018 — Literal-safe codegen for every interpolation site

**Status:** Completed
**Stage:** 18 (per `the-goal-of-this-sequential-sifakis.md` v3)

## Title

Route every Python interpolation site in `marcedit_web/lib/marcedit_import.py`
and `marcedit_web/lib/task_builder.py` through one `lit()` helper, and
add a malicious `.tasksfile` regression corpus that v2 code would
mis-emit.

## Scope

- New module `marcedit_web/lib/codegen_safety.py` exporting a single
  `lit(value)` that wraps `ast.unparse(ast.Constant(value=value))`.
  This is the canonical "safe to splice into Python source" helper for
  the project.
- `marcedit_web/lib/marcedit_import.py` — every f-string slot that
  interpolates a value from the user-supplied tasksfile (tag, ind1,
  ind2, find, code) becomes `{lit(var)}`. The bare-double-quote pattern
  (`f'…"{tag}"…'`) is the failure mode; replace it.
- `marcedit_web/lib/task_builder.py` — same audit on the form-renderer
  side. Routes that are user-supplied even when funneled through the
  form (tag, ind1, ind2, subfield code) all run through `lit()`.
- `tests/test_codegen_safety.py` — unit tests on `lit()` (every
  literal type round-trips, non-literal types raise TypeError) plus an
  8-10 case malicious-tasksfile regression corpus: every emission must
  parse as valid Python and must NOT execute the injected payload when
  run in the sandbox.

## Out of scope

- Changes to the form UI itself. The form already constrains tag/code
  inputs at the Streamlit-widget layer; this stage hardens the codegen
  side so a malicious imported `.tasksfile` can't bypass that layer.
- Sandbox changes (Stage 17 already shipped). The corpus exercises the
  end-to-end import → sandbox path against the existing sandbox.
- Rewriting `transforms.py` helpers. The helpers receive Python
  values, not source strings; they're not on the codegen surface.

## Success Criteria

1. `marcedit_web.lib.codegen_safety.lit` exists and is imported by both
   `marcedit_import.py` and `task_builder.py`.
2. `grep -nE 'f["\x27].*"\{(tag|ind1|ind2|code|find|tok)\}"' marcedit_web/lib/marcedit_import.py
   marcedit_web/lib/task_builder.py` returns no matches — every site
   that used to splice user data into a string literal now goes through
   `lit()`.
3. The 8-10 case malicious corpus under
   `tests/fixtures/malicious_tasksfiles/` converts cleanly via
   `convert_tasksfile_text`, every emitted body parses as Python
   (`ast.parse(body)` succeeds), and the canary file the sandbox
   would create if an injected payload escaped does NOT appear.
4. `pytest -q` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_codegen_safety.py
docker compose run --rm marcedit-web pytest -q
```
