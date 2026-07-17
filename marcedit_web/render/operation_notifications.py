"""Persistent in-app operation alerts and compact queue status."""

from __future__ import annotations

from typing import Any

import streamlit as st

from marcedit_web.lib import operations, runmode


_SEEN_KEY = "operation_notifications_seen_this_session"


def render_header_bell(user_email: str) -> None:
    """Render durable unread alerts using native Streamlit controls."""
    if not runmode.is_private():
        return
    notifications = operations.list_unread_notifications(user_email)
    with st.popover(
        f"Notifications ({len(notifications)})",
        icon=":material/notifications:",
    ):
        if not notifications:
            st.caption("No unread operation notifications.")
            return
        for notification in notifications:
            operation_id = int(notification["id"])
            _render_notice(notification, prominent=False)
            st.page_link(
                "views/D_Operations.py",
                label=f"View operation {operation_id}",
                icon=":material/open_in_new:",
            )
            if st.button(
                "Mark read",
                key=f"operation_notification_read_{operation_id}",
                icon=":material/done:",
            ):
                operations.acknowledge_notification(
                    operation_id,
                    by=user_email,
                )
                st.rerun()
        if st.button(
            "Mark all read",
            key="operation_notifications_read_all",
            icon=":material/done_all:",
        ):
            operations.acknowledge_all_notifications(by=user_email)
            st.rerun()


def render_first_return_notice(user_email: str) -> None:
    """Show the newest durable alert once in this browser session."""
    if not runmode.is_private():
        return
    seen = {
        int(operation_id)
        for operation_id in st.session_state.get(_SEEN_KEY, [])
    }
    notifications = operations.list_unread_notifications(user_email)
    unseen = [row for row in notifications if int(row["id"]) not in seen]
    if not unseen:
        return
    notification = unseen[0]
    operation_id = int(notification["id"])
    seen.update(int(row["id"]) for row in notifications)
    st.session_state[_SEEN_KEY] = sorted(seen)
    _render_notice(notification, prominent=True)
    st.page_link(
        "views/D_Operations.py",
        label=f"View operation {operation_id}",
        icon=":material/pending_actions:",
    )


def render_sidebar_summary(user_email: str) -> None:
    """Render source-visible queue counts in the shared private sidebar."""
    if not runmode.is_private():
        return
    counts = operations.operation_status_counts(user_email)
    with st.sidebar:
        st.caption(
            "Operations: "
            f"{counts['queued']} queued · {counts['running']} running · "
            f"{counts['attention']} attention"
        )
        st.page_link(
            "views/D_Operations.py",
            label="Open Operations",
            icon=":material/pending_actions:",
        )


def _render_notice(notification: dict[str, Any], *, prominent: bool) -> None:
    operation_id = int(notification["id"])
    state = str(notification["state"])
    error_count = int(notification["error_count"])
    if state == "failed":
        message = f"Operation {operation_id} failed."
        if prominent:
            message += " Open Operations to review the error details."
        st.error(message)
    elif state == "cancelled":
        message = f"Operation {operation_id} was cancelled by another user."
        if prominent:
            message += " Open Operations to review."
        st.warning(message)
    elif error_count:
        message = (
            f"Operation {operation_id} completed with {error_count} record "
            f"error{'s' if error_count != 1 else ''}."
        )
        if prominent:
            message += " Open Operations to review."
        st.warning(message)
    else:
        message = f"Operation {operation_id} completed successfully."
        if prominent:
            message += " The result is ready in Operations."
        st.success(message)
