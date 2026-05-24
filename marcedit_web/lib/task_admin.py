"""Admin allowlist for the Code view in the Tasks page.

Standard users (form-builder default) can compose tasks from the typed
operation palette in ``task_builder.OPERATIONS_PALETTE``. Admin users
additionally have the streamlit-ace Code view available to write raw
Python task bodies. Both paths run through the sandbox in
:mod:`marcedit_web.lib.sandbox` — the trust gate here is purely about
who can author arbitrary code, not about whether it runs sandboxed.

Configuration:

* ``MARCEDIT_WEB_ADMINS=user@a.edu,user@b.edu`` — comma-separated list
  of eppns / REMOTE_USERs that gain Code view access.
* ``MARCEDIT_WEB_ADMINS=*`` — dev escape hatch; everyone is admin.
* Unset → no admins (form-builder only).
"""

from __future__ import annotations

import os


_ENV_VAR = "MARCEDIT_WEB_ADMINS"


def admin_list() -> list[str]:
    """Return the configured admin allowlist (or empty list)."""
    raw = os.environ.get(_ENV_VAR, "").strip()
    if not raw:
        return []
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def is_admin(user: str) -> bool:
    """True if ``user`` may use the Code view in the Tasks page.

    A wildcard ``*`` entry in the allowlist admits everyone — useful
    in dev. Empty allowlist means form-builder-only mode.
    """
    if not user:
        return False
    admins = admin_list()
    if "*" in admins:
        return True
    return user in admins
