Title: Account button label wraps mid-word on smaller screens

Scope:
- The auth header control (App.py `_render_auth_header`) renders
  "Account" inside a narrow spacer column (`st.columns([6, 1])`).
  On smaller viewports the column shrinks below the label width and
  the text breaks mid-word ("Accoun / t").
- Keep the label on one line at any viewport width without changing
  the header's right-aligned layout.

Success Criteria:
- At narrow viewport widths the popover label renders on a single
  line (no mid-word break).
- The signed-out "Sign in with Google" button gets the same guard.
- A test pins the no-wrap guard so it is not accidentally removed.
- Runtime before/after verification at a narrow viewport.

Status: In-Progress
