# TASK-113: Highlight changed record lines before and after save

## Title

Show changed MARC lines in the record editor preview and save feedback.

## Scope

- Compare the original record with the edited draft.
- Highlight added, removed, and changed lines in the preview workflow.
- Prefer existing diff utilities where practical.

## Success Criteria

- Catalogers can see exactly which lines changed before confirming save.
- Saved-record feedback can point back to the changed lines.
- The highlighting remains readable for long variable fields.

## Status

Completed

## Verification

- `docker compose run --rm marcedit-web pytest tests/test_collaboration_ui_helpers.py tests/test_structured_record_editor.py tests/test_view_edit.py`
- `docker compose run --rm marcedit-web pytest -ra`
