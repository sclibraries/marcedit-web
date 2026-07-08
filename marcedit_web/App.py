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

from dataclasses import dataclass

import streamlit as st

from marcedit_web.lib import access_gate, db, identity, runmode


@dataclass(frozen=True)
class PageSpec:
    """Lightweight page descriptor — fully constructable outside a Streamlit runtime.

    ``st.Page`` early-returns from its ``__init__`` when there is no
    ``ScriptRunContext``, leaving ``_url_path`` and ``_title`` unset and
    making ``.url_path`` inaccessible in tests. ``PageSpec`` records the
    same information in plain Python so ``build_pages`` is unit-testable
    without a live Streamlit process.
    """

    url_path: str
    title: str
    script: str
    icon: str
    default: bool = False


def build_pages(public: bool) -> dict[str, list[PageSpec]]:
    """Return the section->pages dict for the current run mode.

    Public mode exposes only the read-only / deterministic-transform
    pages (Home upload, View, Validate, Report, Marc Tools). The
    Task Builder / sandbox, Workspace, MarcEditor, Diff, Dedupe, and
    Find pages are NOT registered in public mode — the sandbox path is
    absent by construction, not gated at runtime.
    """
    home = PageSpec(
        url_path="Home", title="Home",
        script="views/00_Home.py", icon=":material/upload_file:", default=True,
    )
    inspect_pages = [
        PageSpec(url_path="View", title="View",
                 script="views/1_View.py", icon=":material/visibility:"),
        PageSpec(url_path="Validate", title="Validate",
                 script="views/2_Validate.py", icon=":material/rule:"),
        PageSpec(url_path="Report", title="Report",
                 script="views/3_Report.py", icon=":material/insights:"),
    ]
    marctools = PageSpec(
        url_path="MarcTools", title="Marc Tools",
        script="views/9_MarcTools.py", icon=":material/swap_horiz:",
    )

    if public:
        return {
            "Start": [home],
            "Inspect": inspect_pages,
            "Convert": [marctools],
        }

    return {
        "Start": [
            home,
            PageSpec(url_path="Jobs", title="Jobs",
                     script="views/B_Jobs.py", icon=":material/folder_shared:"),
            PageSpec(url_path="Workspace", title="Workspace",
                     script="views/0_Workspace.py", icon=":material/dashboard:"),
        ],
        "Inspect": [
            PageSpec(url_path="View", title="View",
                     script="views/1_View.py", icon=":material/visibility:"),
            PageSpec(url_path="Find", title="Find",
                     script="views/7_Find.py", icon=":material/search:"),
        ] + inspect_pages[1:],
        "Edit": [
            PageSpec(url_path="MarcEditor", title="MarcEditor",
                     script="views/5_MarcEditor.py", icon=":material/edit_note:"),
            PageSpec(url_path="Tasks", title="Tasks",
                     script="views/4_Tasks.py", icon=":material/play_arrow:"),
        ],
        "Reconcile": [
            PageSpec(url_path="Diff", title="Diff",
                     script="views/6_Diff.py", icon=":material/compare_arrows:"),
            PageSpec(url_path="Dedupe", title="Dedupe",
                     script="views/8_Dedupe.py", icon=":material/filter_alt:"),
            marctools,
        ],
        "Admin": [
            PageSpec(url_path="Admin", title="Admin",
                     script="views/A_Admin.py", icon=":material/admin_panel_settings:",
                     default=False),
        ],
    }


def _to_st_pages(specs: dict[str, list[PageSpec]]) -> dict[str, list]:
    """Convert a ``build_pages`` result into ``st.Page`` objects for ``st.navigation``.

    Only called inside the ``if __name__ == "__main__"`` guard so that
    ``st.Page`` construction (which requires a Streamlit runtime context)
    never executes during import or testing.
    """
    return {
        section: [
            st.Page(
                spec.script,
                title=spec.title,
                url_path=spec.url_path,
                icon=spec.icon,
                default=spec.default,
            )
            for spec in page_specs
        ]
        for section, page_specs in specs.items()
    }


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


if __name__ == "__main__":
    # Public unit has no catalog DB; only init the schema in private mode.
    if runmode.is_private():
        db.init_schema()

    st.set_page_config(
        page_title="marcedit-web",
        page_icon="\N{BOOKS}",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _render_auth_header()
    access_gate.enforce_access()   # private-mode gate; no-op in public

    st.navigation(_to_st_pages(build_pages(public=runmode.is_public()))).run()
