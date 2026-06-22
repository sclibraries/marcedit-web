"""Deployment run-mode selector (TASK-088).

One artifact runs as two systemd units distinguished by
``MARCEDIT_WEB_MODE``:

* ``public``  — anonymous light tier (View/Validate/Report/MarcTools),
  no catalog DB, no sandbox page.
* ``private`` — authenticated full tier (the default).

Unknown/blank values fail closed to ``private`` so a typo never
accidentally exposes the public surface as the full app — and never
silently drops auth.
"""
from __future__ import annotations

import os

PUBLIC = "public"
PRIVATE = "private"

_MODE_ENV = "MARCEDIT_WEB_MODE"


def app_mode() -> str:
    """Return the resolved run mode: ``"public"`` or ``"private"``."""
    raw = os.environ.get(_MODE_ENV, "").strip().lower()
    return PUBLIC if raw == PUBLIC else PRIVATE


def is_public() -> bool:
    return app_mode() == PUBLIC


def is_private() -> bool:
    return app_mode() == PRIVATE
