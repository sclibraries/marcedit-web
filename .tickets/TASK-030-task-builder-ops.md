# TASK-030 — Task Builder ops expansion

**Status:** Completed
**Stage:** First stage of the MarcEdit Web v3.1 theme.

## Title

Grow the form-builder palette so non-technical catalogers can
reproduce common MarcEdit edit-field / edit-subfield workflows
without leaving form view. Raw Python (the ``custom`` op) stays
admin-only; every new op below is a typed form a standard user can
fill in.

## Scope

Six new typed ops, plus a regex toggle on the existing
``subfield-replace``, plus a field-data regex op. All emit code
through ``task_builder.render_ops_to_python`` and route through the
existing subprocess sandbox at run time. Each lives in the same
``OPERATIONS_PALETTE`` shape so save-and-reopen round-trip
(``# OP:`` marker) keeps working.

### New transforms helpers

Added to ``marcedit_web/lib/transforms.py``. Each is a pure
``(record, ...) -> None`` mutation and ships through
``lit()``-guarded codegen.

| Helper | Signature | Behavior |
| --- | --- | --- |
| ``copy_field`` | ``(record, src_tag, dst_tag)`` | Duplicate every ``src_tag`` field as a new ``dst_tag`` field. Same indicators + subfields. |
| ``move_field`` | ``(record, src_tag, dst_tag)`` | Re-tag every ``src_tag`` field as ``dst_tag``. Implemented as copy + delete-source. |
| ``add_subfield_to_fields`` | ``(record, tag, code, value, *, position="end")`` | Append a subfield to every variable field matching ``tag``. ``position`` is ``"end"`` (default) or ``"start"``. |
| ``delete_subfields`` | ``(record, tag, *codes)`` | Remove subfields with any of the listed codes from every ``tag`` field. |
| ``copy_subfield_within_field`` | ``(record, tag, src_code, dst_code)`` | Within each ``tag`` field, append a new ``$dst_code`` carrying the value of each existing ``$src_code``. |
| ``set_indicators`` | ``(record, tag, *, ind1=None, ind2=None)`` | Override one or both indicators on every ``tag`` field. ``None`` leaves the existing value alone. Control fields skipped (no indicators). |
| ``regex_replace_field_data`` | ``(record, tag, pattern, replacement, *, ignore_case=False)`` | For each ``tag`` field: control fields → ``re.sub`` on ``.data``; variable fields → ``re.sub`` on every subfield value. |

The existing ``subfield-replace`` codegen branch grows two params
(``regex``, ``ignore_case``); the literal branch stays the default
so saved tasks pre-TASK-030 keep their behavior.

### New palette entries

```python
{
    "kind": "copy-field",
    "label": "Copy field",
    "summary": "Duplicate every field with the source tag as a new field with the destination tag.",
    "params": [
        {"name": "src_tag", "label": "Source tag", "type": "text", "required": True},
        {"name": "dst_tag", "label": "Destination tag", "type": "text", "required": True},
    ],
},
{
    "kind": "move-field",
    "label": "Move (re-tag) field",
    "summary": "Re-tag every field; the original is removed.",
    "params": [
        {"name": "src_tag", "label": "Source tag", "type": "text", "required": True},
        {"name": "dst_tag", "label": "Destination tag", "type": "text", "required": True},
    ],
},
{
    "kind": "add-subfield",
    "label": "Add subfield to existing fields",
    "summary": "Append (or prepend) a subfield to every field with the given tag.",
    "params": [
        {"name": "tag", "label": "Tag", "type": "text", "required": True},
        {"name": "code", "label": "Subfield code", "type": "subfield_code", "required": True},
        {"name": "value", "label": "Value", "type": "text", "required": True},
        {"name": "position", "label": "Position", "type": "select",
         "options": [{"value": "end", "label": "Append (end)"},
                     {"value": "start", "label": "Prepend (start)"}],
         "default": "end"},
    ],
},
{
    "kind": "delete-subfield",
    "label": "Delete subfields by code",
    "summary": "Strip the listed subfield codes from every field with the given tag.",
    "params": [
        {"name": "tag", "label": "Tag", "type": "text", "required": True},
        {"name": "codes", "label": "Subfield codes (comma- or space-separated)",
         "type": "text", "required": True,
         "placeholder": "e.g. 5, 9"},
    ],
},
{
    "kind": "copy-subfield",
    "label": "Copy subfield within field",
    "summary": "Within each matching field, copy a subfield value to a different subfield code.",
    "params": [
        {"name": "tag", "label": "Tag", "type": "text", "required": True},
        {"name": "src_code", "label": "Source subfield code", "type": "subfield_code", "required": True},
        {"name": "dst_code", "label": "Destination subfield code", "type": "subfield_code", "required": True},
    ],
},
{
    "kind": "edit-indicators",
    "label": "Set indicators",
    "summary": "Override one or both indicators on every field with the given tag. Leave a field blank to keep the existing value.",
    "params": [
        {"name": "tag", "label": "Tag", "type": "text", "required": True},
        {"name": "ind1", "label": "Indicator 1 (blank = leave alone)", "type": "text"},
        {"name": "ind2", "label": "Indicator 2 (blank = leave alone)", "type": "text"},
    ],
},
{
    "kind": "replace-field-data-by-regex",
    "label": "Replace field data by regex",
    "summary": "Apply a regex find/replace across the data of every field with the given tag. Control fields edit `.data`; variable fields edit each subfield value.",
    "params": [
        {"name": "tag", "label": "Tag", "type": "text", "required": True},
        {"name": "pattern", "label": "Regex pattern", "type": "text", "required": True},
        {"name": "replacement", "label": "Replacement", "type": "text"},
        {"name": "ignore_case", "label": "Case-insensitive", "type": "bool", "default": False},
    ],
},
```

The existing ``subfield-replace`` adds two params at the end:

```python
{"name": "regex", "label": "Treat Find as regex", "type": "bool", "default": False},
{"name": "ignore_case", "label": "Case-insensitive", "type": "bool", "default": False},
```

### Codegen plumbing

Each op gets a new branch in ``task_builder._render_one`` that:
* Builds the helper call via ``lit()`` for every interpolated user
  value (per TASK-018's codegen-safety contract — no bare
  ``"{tag}"`` interpolations).
* Returns ``(code_lines, imports_needed, needs_subfield_import)`` in
  the existing tuple shape.
* For ``delete-subfield``: codes are parsed from the user's comma-
  or-space-separated text input into a list of single-char strings;
  ``lit()``-emitted as positional args to ``delete_subfields``.
* For ``edit-indicators``: a blank ``ind1`` / ``ind2`` field becomes
  ``None`` in the emitted call (helper treats ``None`` as "leave
  alone").
* For ``subfield-replace`` regex path: emit
  ``regex_replace_field_data(..., flags=re.IGNORECASE)`` style.
  ``import re`` added to the file's import block when needed.

### Tests

Per op:
1. ``tests/test_transforms.py`` — helper behavior against the
   sample fixture record. Covers happy path, edge cases (control
   field, missing tag, multiple matches).
2. ``tests/test_task_builder.py`` — codegen output for each op
   contains the expected ``lit()``-rendered helper call; round-
   trip via ``parse_ops_from_source`` produces an equivalent op.
3. Integration: 1–2 end-to-end tests through ``sandbox.run_tasks_subprocess``
   on `tests/fixtures/sample.mrc` confirming the new ops actually
   transform a real MARC record (one targeted test per new
   helper isn't necessary; one combined "happy path through all
   new ops" smoke is enough at the integration layer).

## Out of scope (and why)

- **Conditional ops** ("only if field/subfield exists", "only if
  matches regex"). These need a nested-op structure (current ops
  are flat statements; a conditional wraps another op). That's a
  task-builder architecture change worth its own stage.
- **Normalize punctuation.** Needs a written spec for *which*
  normalizations (trailing periods, ISBD-style trailing-space
  patterns, etc.). Pick those up in a follow-up.
- **Sort fields with protected local tags.** A param on the
  existing ``sort-fields`` op; small but skipped here so this
  stage stays focused.
- **Swap field.** Covered by ``copy-field`` + ``delete-tag`` or
  by two ``move-field`` ops. Not worth a dedicated palette entry.
- **Regex execution timeout.** The subprocess sandbox already
  bounds wall-clock at 30s; a catastrophic backtrack burns one
  task run, parent stays alive. Same model as the existing
  ``delete-856-url-regex`` op.

## Success Criteria

1. All 6 new ops appear in the palette dropdown for non-admin
   users (``custom`` filter unchanged).
2. ``subfield-replace`` renders the ``Treat Find as regex`` +
   ``Case-insensitive`` checkboxes; existing saved tasks
   (regex=False default) keep their literal behavior.
3. ``replace-field-data-by-regex`` op exists; saving it then
   reopening from disk lands back in form view.
4. Every emitted helper call goes through ``lit()`` for user-
   supplied values (grep verification: no
   ``f'…"{tag}"…'`` introduced).
5. New helpers in ``transforms.py`` covered by unit tests against
   the sample fixture.
6. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q tests/test_transforms.py tests/test_task_builder.py
docker compose run --rm marcedit-web pytest -q
```
