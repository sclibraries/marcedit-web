Title: Quick batch operations outside FOLIO container codes

Scope:
- Design and implement a Tasks-page "Quick batch operations" area for common
  one-shot MARC cleanup actions that do not need saved task authoring.
- Include the approved first operation families: Leader value setter, 008 form
  of item, 040 cleanup, 856 URL tools, OCLC 035 cleanup, local 9xx cleanup,
  and 655 genre/form cleanup.
- Keep FOLIO container code standardization in 035 $9 out of this ticket; it
  will be a separate operation with its own controlled code list.

Success Criteria:
- A written design spec exists and is approved before implementation planning.
- The implementation plan references this ticket.
- Canned operations are preview-first, deterministic, and avoid generated
  Python execution.
- Advanced conditional or exception-heavy workflows remain in the existing task
  builder/code path.

Status: Todo
