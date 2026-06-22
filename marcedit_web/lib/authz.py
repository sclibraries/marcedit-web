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


_VALID_ROLES = ("admin", "cataloger")


def approve_user(email: str, *, by: str, role: str = "cataloger") -> None:
    if role not in _VALID_ROLES:
        raise ValueError(f"unknown role: {role!r}")
    email = email.lower()
    now = _now()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(email, role, status, created_at,"
            " approved_at, approved_by)"
            " VALUES (?, ?, 'approved', ?, ?, ?)"
            " ON CONFLICT(email) DO UPDATE SET"
            "   role=excluded.role, status='approved',"
            "   approved_at=excluded.approved_at, approved_by=excluded.approved_by",
            (email, role, now, now, by),
        )
    audit_event("auth.approved", user=email)


def revoke_user(email: str, *, by: str) -> None:
    email = email.lower()
    with db.connect() as conn:
        conn.execute(
            "UPDATE users SET status='revoked' WHERE email=?", (email,)
        )
    audit_event("auth.revoked", user=email)


def set_role(email: str, role: str, *, by: str) -> None:
    if role not in _VALID_ROLES:
        raise ValueError(f"unknown role: {role!r}")
    with db.connect() as conn:
        conn.execute(
            "UPDATE users SET role=? WHERE email=?", (role, email.lower())
        )


def list_users() -> list:
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT email, role, status, created_at, approved_at, approved_by"
            " FROM users ORDER BY email"
        )]


def list_pending() -> list:
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT email, created_at FROM users WHERE status='pending'"
            " ORDER BY created_at"
        )]


def list_domains() -> list:
    with db.connect() as conn:
        return [r["domain"] for r in conn.execute(
            "SELECT domain FROM allowed_domains ORDER BY domain"
        )]


def add_domain(domain: str, *, by: str) -> None:
    domain = domain.strip().lower()
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO allowed_domains(domain, added_at, added_by)"
            " VALUES (?, ?, ?)",
            (domain, _now(), by),
        )
    audit_event("auth.domain_added", user=by)


def remove_domain(domain: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM allowed_domains WHERE domain=?", (domain.strip().lower(),)
        )
