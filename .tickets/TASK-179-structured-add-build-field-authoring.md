Title: Add structured Add Field and Build Field task authoring

Parent: TASK-174

Scope:
- Improve the existing Tasks form rather than introduce a second editor or
  storage path.
- Replace Add Field JSON entry with ordered, repeatable subfield-code and value
  rows.
- Replace normal Build Field raw-template entry with typed literal,
  source-field, and subfield segments.
- Keep the generated MARC mnemonic visible and explain each technical token;
  do not hide the underlying MARC behavior.
- Provide deterministic, read-only previews and plain-language summaries.
- Save and reopen through the existing form-task representation.
- Convert only legacy Add Field and Build Field signatures whose meanings are
  known exactly; keep ambiguous imports visible and blocking.
- Start a checked-in task-authoring syntax reference using sanitized examples
  derived from Smith CORE Instance and Smith CORE Holdings and Items.
- Record confidence-rated local MarcEdit package research without copying or
  redistributing proprietary binaries, configuration files, or documentation.
- Leave existing AI drafting prompts, generators, and legacy operation
  contract unchanged; normalize accepted drafts only when they enter the
  deterministic form editor. Defer AI redesign or retirement to a separately
  ticketed future release.

Success Criteria:
- A cataloger can create, reorder, and remove Add Field subfield rows without
  writing JSON.
- A cataloger can build 035 and 876 fields from literals, 003, and 001 using
  structured controls without writing a raw template.
- Every structured operation shows a plain-language summary, technical MARC
  mnemonic, token explanation, and deterministic first-record preview when a
  record is available.
- Invalid tags, indicators, subfield codes, empty definitions, unresolved
  source references, and lossy round trips block structured save or preview
  with actionable messages.
- New imports with unresolved instructions are not persisted. Existing
  unresolved Add/Build instructions remain visible and preservable during
  unrelated edits but block task execution until recreated.
- Structured Add Field and Build Field definitions survive save and reopen
  without changing order, types, or values.
- Existing AI drafting continues to accept and emit its current legacy
  Add/Build shape, while editor handoff normalizes that shape deterministically.
- Exact supported legacy signatures convert losslessly; malformed or
  ambiguous signatures remain visible and cannot execute.
- Sanitized synthetic tests cover the relevant Smith CORE signatures. The real
  institutional corpus remains untracked and is only a local supplementary
  check that skips loudly when absent.
- Focused and complete supported Docker suites pass with every skip reported.
- Independent review has no unresolved Critical or Important findings.

Status: In-Progress

Design:
- `docs/superpowers/specs/2026-07-30-task-179-structured-add-build-field-authoring-design.md`

Plan:
- `docs/superpowers/plans/2026-07-30-task-179-structured-add-build-field-authoring.md`
