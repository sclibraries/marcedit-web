"""Tasks — thin shim around :mod:`marcedit_web.render.tasks`."""

from __future__ import annotations

import streamlit as st

from marcedit_web.lib import session
from marcedit_web.render import sidebar_status
from marcedit_web.render import tasks as render_tasks

st.set_page_config(page_title="Tasks · marcedit-web", layout="wide")
session.init()

st.title("Tasks")
st.caption(
    "Build, import, and run named transforms over the loaded batch. "
    "Tasks persist on disk under `data/tasks/users/<you>/` and survive "
    "across sessions."
)

sidebar_status()

render_tasks.render()
