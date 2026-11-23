# ADR 0003: Public mode is removed

Date: 2026-11-23 · Status: accepted (owner) · Removes invariant 6 when built.

**Context.** Public mode serves read-only tools without sign-in. Only the private service was active on
the host when last checked (2026-09-10).

**Decision.** The rewrite has one mode: signed-in. Requests without a valid identity are refused.

**Costs.** People without an account lose the read-only tools.
