# TASK-048 — UI polish: hide Deploy, move sign-in to top-right

**Status:** Completed
**Stage:** Post-OAuth UX cleanup.

## Title

Two end-user-facing UI issues from TASK-047 review:

1. Streamlit's default ``Deploy`` button (top-right of the page,
   inside Streamlit's own toolbar) makes the app look like a dev
   environment and confuses end users who think it's an action
   they should take.
2. The OAuth sign-in/out block landed near the bottom of the
   sidebar — ``st.navigation`` always renders nav at the top of
   the sidebar regardless of when the page writes other content
   there, so anything pushed via ``with st.sidebar:`` ends up
   beneath the nav. Standard app convention puts identity
   controls in the top-right of the page.

## Scope

- **`.streamlit/config.toml`** — set ``[client] toolbarMode = "minimal"``.
  This hides Deploy + the entire Streamlit dev toolbar. The ≡ menu
  still works for users (it's part of Streamlit's framework, not the
  toolbar). Documented in
  https://docs.streamlit.io/develop/api-reference/configuration/config.toml.
- **`marcedit_web/App.py`**:
  * Remove the sidebar auth block; identity belongs at the top
    of the page, not in the sidebar.
  * Render a top-of-page auth bar using a right-aligned column,
    BEFORE ``st.navigation(_pages).run()``. The bar shows on every
    page because everything before ``.run()`` runs on every page.
  * Logged-in: ``st.popover`` showing the account icon + email,
    with a "Sign out" button inside the popover. The popover is
    the Streamlit-idiomatic way to do an account menu.
  * Not logged in (OAuth configured): a "Sign in with Google"
    button right-aligned.
  * OAuth not configured: render nothing — keeps the dev path
    visually identical to pre-OAuth.

## Out of scope

- A custom CSS injection to position content INSIDE Streamlit's
  framework toolbar / header. Fragile across Streamlit releases.
- Replacing the Streamlit ≡ menu. Keep it; "About" and "Settings"
  are useful affordances even for end users.
- Other sidebar reorg — TASK-045 already did the section layout
  and that's working.

## Success Criteria

1. Deploy button no longer visible after rebuild + restart.
2. Right-aligned account control appears at the top of every
   page (Home, View, Workspace, Tasks, etc.), above the page
   content, regardless of which page is selected.
3. Clicking the account icon (logged in) opens the popover with
   the email + Sign out.
4. With OAuth not configured (no ``[auth]`` in secrets), the
   page top is identical to pre-TASK-047 — no auth UI artifacts.
5. ``pytest -q`` stays green (the change is UI-only; no test
   logic changes).

## Verification commands

```sh
docker compose build marcedit-web
docker compose up -d marcedit-web
docker compose run --rm marcedit-web pytest -q
# Then browser smoke: confirm top-right account control and absence
# of Deploy button.
```
