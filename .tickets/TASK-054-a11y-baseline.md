# TASK-054 — A11y baseline pass

**Status:** Completed
**Stage:** UX cleanup pass — WCAG 2.1 AA-aligned where the
Streamlit framework lets us steer it.

## Title

Three a11y issues surfaced in the page inventory:

1. **Heading hierarchy skips.** Home, MarcTools, Validate, and
   Dedupe go straight from ``st.title`` (h1) to ``st.subheader``
   (h3), skipping h2. Screen readers depend on the level ladder.
2. **`unsafe_allow_html=True` sites.** Two callsites (View's
   help-entry tooltip and Diff's side-by-side HTML table) render
   raw HTML. Need to confirm the inputs are app-controlled and
   either escape them or annotate why safe.
3. **Document the framework's a11y posture.** Streamlit owns most
   of the DOM; operators / accessibility reviewers need to know
   what the app controls vs the framework so audits aren't shaped
   against impossible asks.

## Scope

- **Heading hierarchy fixes.** Replace the first ``st.subheader``
  per page with ``st.header`` so the ladder reads h1 → h2 →
  (h3 sub-sections). Pages to touch:
  * ``views/00_Home.py``: "Upload a MARC file" + "Loaded batch"
    promoted to h2.
  * ``marcedit_web/render/marc_tools.py``: each ``_convert_to_*``
    sub-section's leading subheader → header.
  * ``marcedit_web/render/validate.py``: "Issue table" stays h3
    but the page title in ``views/2_Validate.py`` already
    provides h1; add an h2 above the metrics row so the table
    sits under a sensible level.
  * ``marcedit_web/render/dedupe.py``: review the four section
    subheaders; promote the first to h2.
- **`unsafe_allow_html` audit:**
  * ``render/view.py:228`` — ``tooltips.render_help_entry`` reads
    from the operator-controlled ``data/marc-rules.txt``. Add an
    in-code comment confirming the trust source. No escaping
    change (rules file is ops-managed, not user-uploaded).
  * ``views/6_Diff.py:418`` — ``_render_diff_html(rows)`` builds
    HTML from parsed records. Confirm it escapes field values via
    ``html.escape`` (or wrap if not). Update the helper if needed.
- **`docs/deployment.md`:** new "Accessibility" subsection that
  documents:
  * The WCAG 2.1 AA target and which controls the app owns.
  * What Streamlit's framework provides (color contrast in the
    light theme, focus rings, semantic widgets).
  * How to run a Lighthouse / axe-core audit against the running
    container.

## Out of scope

- Replacing Streamlit's iframe shell with a custom component-level
  audit. The framework's DOM is what it is; we steer only our
  ``st.*`` calls.
- Full keyboard-navigation rewrite. The default Streamlit widgets
  already accept keyboard input; no app-level changes needed.
- Audit tooling automation (running axe-core on every push). Build
  it later if the regression risk warrants it.

## Success Criteria

1. Every page's heading ladder starts at h1 and steps down without
   gaps, verifiable by looking for the pattern in the source.
2. Both ``unsafe_allow_html=True`` callsites have either escaping
   in place or an in-code "trusted source" annotation.
3. ``docs/deployment.md`` has an "Accessibility" subsection
   describing the contract.
4. ``pytest -q`` stays green.

## Verification commands

```sh
docker compose run --rm marcedit-web pytest -q
# Visual / structural check: load each page, inspect with the
# browser dev tools' Accessibility tab, confirm headings step
# down monotonically.
```
