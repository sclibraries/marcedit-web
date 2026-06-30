# TASK-112: Show save-time record readiness before persistence

## Title

Surface MARC/load-readiness validation in the record editor before save.

## Scope

- Confirm which checks are blocking errors versus warnings in the editor save
  flow.
- Reuse the existing MARC parse validation and load-readiness checks from
  TASK-090.
- Show cataloger-readable feedback before a save is persisted.

## Success Criteria

- Invalid MARC still cannot be saved.
- Load-readiness issues such as 006/007/008/336/337/338 problems are visible in
  the save/preview workflow.
- The feedback distinguishes blocking errors from warnings.

## Status

Todo
