# marcedit_web/lib/authz.py
"""Authorization layer above identity resolution (TASK-088).

``identity.current_user()`` answers *who* the request is. This module
answers *whether they may use the private tier and as what role*,
backed by the ``users`` + ``allowed_domains`` tables.

Decision order (first match wins):
  1. anonymous            -> denied
  2. existing users row   -> its (status, role)   [revoked stays revoked]
  3. domain ∈ allowlist   -> auto-provision approved/cataloger
  4. otherwise            -> queue as pending

Side effects (auto-provision, pending insert) emit an ``auth.*`` audit
event. No PII beyond the email already stored in the row.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Optional

from . import db
from .audit import audit_event
from .identity import ANONYMOUS, is_anonymous


@dataclass
class Decision:
    outcome: str            # "approved" | "pending" | "revoked" | "denied"
    role: Optional[str] = None


def _now() -> str:
    return _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def domain_of(email: str) -> str:
    """Lowercased domain part of an email, or '' when there's no '@'."""
    _, _, domain = email.partition("@")
    return domain.strip().lower()


def get_user(email: str) -> Optional[dict]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT email, role, status, created_at, approved_at, approved_by"
            " FROM users WHERE email=?",
            (email.lower(),),
        ).fetchone()
    return dict(row) if row else None


def _is_allowed_domain(domain: str) -> bool:
    if not domain:
        return False
    with db.connect() as conn:
        return conn.execute(
            "SELECT 1 FROM allowed_domains WHERE domain=?", (domain,)
        ).fetchone() is not None


def authorize(email: str) -> Decision:
    """Resolve the access decision for ``email`` (see module docstring)."""
    if is_anonymous(email):
        return Decision("denied")

    email = email.lower()
    existing = get_user(email)
    if existing is not None:
        outcome = existing["status"]
        role = existing["role"] if outcome == "approved" else None
        return Decision(outcome, role)

    now = _now()
    if _is_allowed_domain(domain_of(email)):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO users(email, role, status, created_at,"
                " approved_at, approved_by)"
                " VALUES (?, 'cataloger', 'approved', ?, ?, '__domain__')",
                (email, now, now),
            )
        audit_event("auth.approved", user=email)
        return Decision("approved", "cataloger")

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(email, role, status, created_at)"
            " VALUES (?, 'cataloger', 'pending', ?)",
            (email, now),
        )
    audit_event("auth.pending", user=email)
    return Decision("pending")
