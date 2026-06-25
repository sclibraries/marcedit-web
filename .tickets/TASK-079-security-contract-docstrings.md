# TASK-079 — Document the load-bearing security contracts

**Status:** Todo
**Priority:** Tier 2 — Documentation (security-relevant)
**Source:** Deep code audit 2026-06-17 — docs findings (11 high)

## Title

Add or correct docstrings on the codegen, sandbox, and import functions whose
invariants are security-critical.

## Scope

- State the contract explicitly on `task_builder._render_one` and
  `render_ops_to_python` ("every user-supplied value MUST pass through `lit()`
  / the AST allowlist").
- Add docstrings to `render/tasks.py::_execute_sandboxed_run` and
  `_render_run_panel` (the sandbox execution entry points) and document the
  admin dual-audit behaviour in `_save_callback`.
- Document `marcedit_import.convert_tasksfile` (public entry point) and
  `_emit_add` (subfield interpolation rules), and `tasks.load_user_tasks`
  (AST-only rationale + the `LAST_LOAD_ISSUES` mutable-state clear-on-call
  behaviour).
- Correct misleading docstrings: `db.init_schema` (claims migrations it does
  not perform), `viewer.parse_indices` (claims `ValueError` on malformed but
  leaks raw `int()` errors), `editor.save_user_task` (omits the pre-flight
  compile step). Add the missing `session.current_filename` docstring.

## Success Criteria

1. Each listed symbol has an accurate docstring naming its security/contract
   invariants.
2. Misleading docstrings are corrected to match the code.
3. Documentation-only — no behaviour change; existing tests still pass.
