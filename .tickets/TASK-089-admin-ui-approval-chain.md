# TASK-089 — Admin UI approval chain

**Status:** Completed
**Priority:** Tier 3 — local/private access operability
**Source:** Follow-up to TASK-088 after local login landed in pending state

## Title

Make the TASK-088 approval chain usable through the private Admin UI after bootstrap admin seeding.

## Scope

- Keep the approval flow Admin UI-only after the first bootstrap admin exists.
- Use `MARCEDIT_WEB_ADMIN_EMAILS` as the supported first-admin path.
- Ensure docs and tests explain where pending users land and how an admin approves them.
- Avoid adding a separate operator CLI or manual SQLite approval workflow.

## Success Criteria

1. A configured bootstrap admin reaches the private Admin page.
2. A non-allowlisted login appears in the Admin page pending approvals list.
3. Admin approval changes the user to approved cataloger access.
4. Documentation clearly names the `users` and `allowed_domains` tables and the env-based bootstrap path.
5. Focused approval-flow tests pass.
