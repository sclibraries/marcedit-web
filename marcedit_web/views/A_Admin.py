"""Admin page — user approvals, roles, allowed domains (TASK-088).

Registered only on the private unit (see App.build_pages). Guarded so
that only an approved admin can act; catalogers get a refusal. The
heavy lifting lives in lib/authz.py (unit-tested); this page is thin UI.
"""
from __future__ import annotations

import streamlit as st

from marcedit_web.lib import authz, session


def is_admin(state) -> bool:
    """True when the session role is admin. Accepts a dict-like state."""
    try:
        return state.get("role") == "admin"
    except AttributeError:
        return False


def _render() -> None:
    session.init_page()  # state defaults + (private) auth already enforced upstream
    st.title("Admin")

    if not is_admin(st.session_state):
        st.error("**Admins only.** Your account does not have admin access.")
        st.stop()

    me = session.current_user_id()

    st.subheader("Pending approvals")
    pending = authz.list_pending()
    if not pending:
        st.caption("No accounts awaiting approval.")
    for row in pending:
        cols = st.columns([4, 1, 1])
        cols[0].write(row["email"])
        if cols[1].button("Approve", key=f"ap_{row['email']}"):
            authz.approve_user(row["email"], by=me)
            st.rerun()
        if cols[2].button("Deny", key=f"dn_{row['email']}"):
            authz.revoke_user(row["email"], by=me)
            st.rerun()

    st.subheader("Allowed domains")
    st.write(", ".join(authz.list_domains()) or "_none_")
    new_domain = st.text_input("Add domain", key="add_domain")
    if st.button("Add", key="add_domain_btn") and new_domain.strip():
        authz.add_domain(new_domain, by=me)
        st.rerun()

    st.subheader("Users")
    for row in authz.list_users():
        cols = st.columns([3, 2, 2])
        cols[0].write(f"{row['email']} — {row['status']}")
        cols[1].write(row["role"])
        if row["status"] == "approved" and cols[2].button(
            "Toggle admin", key=f"role_{row['email']}"
        ):
            new_role = "cataloger" if row["role"] == "admin" else "admin"
            authz.set_role(row["email"], new_role, by=me)
            st.rerun()


if __name__ == "__main__":
    _render()
