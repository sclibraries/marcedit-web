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

Verification:
- `docker run --rm -v $PWD/marcedit_web:/app/marcedit_web:ro -v $PWD/tests:/app/tests:ro -v $PWD/data:/app/data:ro -v $PWD/docker-compose.yml:/app/docker-compose.yml:ro marcedit-web:dev pytest -ra tests/`
  - 1016 passed, 7 skipped (env-conditional deploy tests).
- `python3 -m pytest tests/test_deploy_units.py tests/test_docker_compose_config.py` (host)
  - 8 passed.
- Browser verification (Playwright, stubbed OAuth identity): before the
  fix the label wrapped mid-word at 750px (button 86px tall); after the
  fix both "Account" and "Sign in with Google" render on one line at
  750px and 420px viewports (button 40px), flush right, fully
  on-screen.

Status: Completed
