# TASK-076 — AST allowlist for non-admin and imported task bodies

**Status:** Todo
**Priority:** Tier 1 — Hardening (makes a trust guarantee code-enforced)
**Source:** Deep code audit 2026-06-17 — horizon hardening (codegen trust boundary)

## Title

Code-enforce the "no raw Python for non-admins" guarantee with an AST allowlist
validating every imported / non-admin task body before storage and execution.

## Scope

- Today the guarantee rests on discipline across ~10 `lit()` sites plus the
  admin gate; a non-admin can still import a `.tasks` file whose emitted code
  (`lib/marcedit_import.py:452-481`) is concatenated and later `exec`'d
  (`sandbox.py:176`).
- Add an AST validator accepting only the constructs the form-builder /
  transpiler emit: calls to whitelisted `transforms` helpers with literal
  arguments. Reject `import`, dunder attribute access, `exec`/`eval`,
  comprehension-based escapes, etc.
- Apply at MarcEdit body assembly and before any non-admin / imported body
  reaches the sandbox. Admin Code-view bodies stay exempt (already gated).

## Success Criteria

1. A crafted `.tasks` import that would emit a non-whitelisted construct is
   rejected at import/storage time with a clear message.
2. All existing form-builder output and valid MarcEdit imports pass the
   allowlist unchanged.
3. The allowlist is the enforced boundary (not reliant on `lit()` discipline
   alone) and is documented at the codegen functions (coordinated with
   TASK-079).
4. Focused tests and the Docker test suite pass before completion.
