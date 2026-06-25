# TASK-062 — Remove AI draft wording from task review UI

**Status:** Completed

## Title

Rename cataloger-facing task draft wording so deterministic drafts are not
presented as AI-generated.

## Scope

- Replace visible Tasks-page labels and warnings that say "AI draft" with
  neutral "task draft" wording.
- Keep Gemini fallback wording explicit only where the optional Gemini button
  appears.
- Avoid broad internal renames unless needed for visible behavior.

## Success Criteria

1. The draft review heading says "Task draft review".
2. Blocking review warnings say "task draft" or "draft" rather than "AI draft".
3. Clear/use button labels do not imply AI generated the draft.
4. Focused tests pass.
