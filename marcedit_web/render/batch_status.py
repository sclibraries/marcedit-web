"""Loaded-batch status helpers shared by workflow views."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session


def loaded_batch_status() -> None:
    """Render the active MARC batch in the main page body."""
    store = session.current_store()
    if store is None:
        st.info("No MARC batch is loaded.")
        return

    filename = session.current_filename() or "(unnamed)"
    record_count = f"{store.count():,} records"
    malformed = store.malformed_count()
    parts = [f"**Loaded batch:** `{filename}`", record_count]
    if malformed:
        parts.append(f"{malformed:,} malformed/skipped")
    st.markdown(" · ".join(parts))
