"""marcedit-web — navigation entrypoint.

This is the Docker CMD target (``streamlit run marcedit_web/App.py``).
It owns the global ``st.set_page_config`` call and uses
``st.navigation`` (Streamlit 1.36+) to group pages into task-aligned
sections — see TASK-045.

The actual landing-page content lives in
``marcedit_web/views/00_Home.py``; ``st.navigation`` selects which
page script runs and that page renders its own body.

The page scripts live under ``marcedit_web/views/`` (not ``pages/``)
on purpose — Streamlit auto-discovers ``pages/`` and registers each
file as a v1 multi-page-app route, which collides with the
``st.navigation`` registrations in this file. Renaming the directory
moves the page scripts off that auto-discovery path.

Sign-in UI (TASK-047 + TASK-048): when OAuth is configured in
``.streamlit/secrets.toml`` (``[auth]`` section present), a Google
sign-in / sign-out control renders top-right above the page body
on every page. When OAuth is not configured, the page renders
exactly as it did pre-OAuth.
"""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import db, identity

# Ensure the SQLite schema exists before any page emits an audit
# event. Idempotent — multiple Streamlit reruns of this module
# short-circuit on the in-process flag.
db.init_schema()

st.set_page_config(
    page_title="marcedit-web",
    page_icon="\N{BOOKS}",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _render_auth_header() -> None:
    """Render the sign-in / sign-out control at the top-right of the page.

    Sits above the page body because anything written before
    ``st.navigation(_pages).run()`` runs on every page render.
    Right-aligned via an empty spacer column. No-op when OAuth
    isn't configured — the dev path stays visually unchanged.

    Streamlit's framework toolbar (top-right of the browser chrome)
    isn't user-content; that's why this lives at the top of the page
    body rather than in Streamlit's header strip.
    """
    if not identity.is_oauth_configured():
        return
    try:
        # Wide spacer + narrow control column → control sits flush right.
        # The ratio is empirical; small enough that the popover label
        # ("Account") doesn't wrap.
        _, right = st.columns([6, 1])
        with right:
            email = identity.oauth_user()
            if email:
                with st.popover(
                    "Account",
                    icon=":material/account_circle:",
                    width="stretch",
                ):
                    st.caption(email)
                    if st.button(
                        "Sign out", key="auth_signout", width="stretch"
                    ):
                        st.logout()
            else:
                if st.button(
                    "Sign in with Google",
                    key="auth_signin",
                    icon=":material/login:",
                    type="primary",
                    width="stretch",
                ):
                    st.login("google")
    except Exception:
        # Pre-1.42 Streamlit (no st.login/st.logout/st.popover) —
        # fall through quietly so the rest of the app still renders.
        return


_render_auth_header()


# Task-aligned sections. The dict key is the sidebar section header;
# the order in this dict is the order rendered in the sidebar.
# ``url_path=`` preserves the legacy URLs so direct links / bookmarks
# (``/View``, ``/Tasks``, etc.) keep working.
_pages = {
    "Start": [
        st.Page(
            "views/00_Home.py", title="Home",
            url_path="Home", icon=":material/upload_file:", default=True,
        ),
        st.Page(
            "views/0_Workspace.py", title="Workspace",
            url_path="Workspace", icon=":material/dashboard:",
        ),
    ],
    "Inspect": [
        st.Page(
            "views/1_View.py", title="View",
            url_path="View", icon=":material/visibility:",
        ),
        st.Page(
            "views/7_Find.py", title="Find",
            url_path="Find", icon=":material/search:",
        ),
        st.Page(
            "views/2_Validate.py", title="Validate",
            url_path="Validate", icon=":material/rule:",
        ),
        st.Page(
            "views/3_Report.py", title="Report",
            url_path="Report", icon=":material/insights:",
        ),
    ],
    "Edit": [
        st.Page(
            "views/5_MarcEditor.py", title="MarcEditor",
            url_path="MarcEditor", icon=":material/edit_note:",
        ),
        st.Page(
            "views/4_Tasks.py", title="Tasks",
            url_path="Tasks", icon=":material/play_arrow:",
        ),
    ],
    "Reconcile": [
        st.Page(
            "views/6_Diff.py", title="Diff",
            url_path="Diff", icon=":material/compare_arrows:",
        ),
        st.Page(
            "views/8_Dedupe.py", title="Dedupe",
            url_path="Dedupe", icon=":material/filter_alt:",
        ),
        st.Page(
            "views/9_MarcTools.py", title="Marc Tools",
            url_path="MarcTools", icon=":material/swap_horiz:",
        ),
    ],
}

st.navigation(_pages).run()
