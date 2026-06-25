# TASK-029 — Security review fixes

**Status:** Completed
**Stage:** Post-v3 — security review follow-up.

## Title

Cataloger-led security review surfaced seven findings; this ticket
addresses them in priority order.

## Scope

### High 1 — Non-admin custom-op read-only

A non-admin can't *add* a `custom` op from the palette (we filter it
out of the dropdown), but an imported / pre-existing task that
already contains a `custom` block renders as an editable code
textarea in the form editor. ``task_builder._render_one`` then emits
that code verbatim on save. Net effect: a non-admin can paste
arbitrary Python into the editor and save it.

Fix: thread ``is_admin`` through ``_render_form_editor`` →
``_render_param_input``. When ``ptype == "code"`` and the user is
not admin, render the code as a read-only ``st.code(...)`` block
with a notice; preserve the existing params value untouched so the
saved task body remains as imported. Don't accept user mutations.

### High 2 — AST-only task discovery

``tasks.load_user_tasks`` runs every task file via
``spec.loader.exec_module()`` to trigger ``@task(...)`` registration.
Even though the run path is sandboxed, *discovery* still imports
modules into the parent Streamlit process — a sandboxed task that
manages to write to ``data/tasks/users/<eppn>/`` plants code that
executes outside the sandbox on the next page render.

Fix: replace exec-based discovery with AST parsing.
``editor.parse_user_task_file`` already does the right thing (returns
``{name, description, body}`` via ``ast.parse`` only). Rewrite
``load_user_tasks`` to use it. ``Task.fn`` becomes optional — the
sandbox runs from ``body`` text, not from a callable.

### High 3 — Sandbox doc accuracy

Verify nothing in the codebase / tickets / docs claims the sandbox
blocks ``subprocess`` or absolute-path writes. The existing
``sandbox.py`` docstring is already honest ("not a full sandbox"),
but check for overclaims elsewhere. Acceptable as defense-in-depth;
just don't oversell.

### Medium 1 — Container filesystem hardening

``Dockerfile`` currently ``chown -R marcedit:marcedit /app``. A
sandboxed task that escapes the intended path could overwrite app
source. Restrict to ``/app/data`` so application code stays
root-owned and read-only at runtime. Healthcheck + Streamlit still
work because the marcedit user has read access via default 0755 dir
permissions.

### Medium 2 — Stage 22 literal cleanup

``render/tasks.py:358`` still uses ``st.session_state['tasks_editor_original_name']``
instead of ``K_EDITOR_ORIGINAL_NAME``. One-line fix.

### Medium 3 — Audit docs alignment

``lib/audit.py`` docstring and ``deployment.md`` claim a
``download-issued`` event is emitted; no callsite actually emits it.
Stage 19 scoped audit to security-relevant events only and downloads
of bytes the user already had access to upload aren't in that scope.
Remove the claim.

### Low 1 — Home upload-rejection fall-through

``Home.py`` shows "Upload rejected: …" then continues to render
"No records found in the uploaded file." Short-circuit on the
``error`` branch of ``upload_summary``.

### Low 2 — Working-tree artifacts

Add ``data/audit/`` and ``*.png`` (or just the per-run screenshot
prefixes used by Playwright) to ``.gitignore``.

## Out of scope

- Capability isolation in the sandbox (seccomp, network namespace,
  chroot). True isolation requires container privileges and is its
  own work item.
- Switching admin Code-view tasks to the same data-only discovery
  path. Admin code is trusted in this model.

## Success Criteria

1. With a non-admin user, opening an imported task that contains a
   `custom` block shows the code as read-only; saving doesn't
   accept user mutations to the custom code.
2. ``tasks.load_user_tasks`` no longer calls ``exec_module``. Task
   discovery works via AST parsing only.
3. Running container shows ``/app/marcedit_web`` owned by root
   (uid 0), ``/app/data`` owned by uid 10001.
4. The literal `'tasks_editor_original_name'` no longer appears
   outside the constant declaration.
5. ``audit.py`` / ``deployment.md`` accurately list emitted events.
6. Upload rejection on Home shows the error and NOT "No records
   found".
7. ``pytest -q`` stays green.
8. ``.gitignore`` covers audit logs + ad-hoc screenshot artifacts.

## Verification commands

```sh
docker compose build && docker compose run --rm marcedit-web pytest -q
docker compose run --rm marcedit-web ls -la /app/marcedit_web | head
docker compose run --rm marcedit-web ls -la /app/data | head
```
