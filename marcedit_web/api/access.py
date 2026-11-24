"""Request identity and access checks for the versioned API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from flask import g, request

from marcedit_web.lib import authz, identity
from marcedit_web.lib.audit import audit_event


_API_ROOT = "/api/v1"
_HEALTH_PATH = "/api/v1/health"
_ME_PATH = "/api/v1/me"


@dataclass(frozen=True)
class Access:
    email: Optional[str]
    outcome: str
    role: Optional[str]


def check_request(settings):
    """Authorize one API request before its route can read the body."""
    path = request.path
    if path != _API_ROOT and not path.startswith(_API_ROOT + "/"):
        return None
    if path == _HEALTH_PATH:
        return None

    email = settings.dev_user or identity.proxy_user(request.headers)
    if identity.is_anonymous(email):
        access = Access(None, "anonymous", None)
    else:
        decision = authz.authorize(email)
        access = Access(email, decision.outcome, decision.role)
    g.api_access = access

    if access.email is None:
        audit_event(
            "anonymous-action-refused",
            user="anonymous",
            page=path,
            action=request.method,
        )
        return "signed-out", "Sign in to use this service.", 401

    is_me_get = path == _ME_PATH and request.method == "GET"
    if not is_me_get and access.outcome != "approved":
        audit_event("auth." + access.outcome, user=access.email)
        return "not-approved", "Your access is not approved.", 403

    if path == _API_ROOT + "/admin" or path.startswith(_API_ROOT + "/admin/"):
        if access.role != "admin":
            audit_event("auth.admin-only", user=access.email)
            return "admin-only", "Administrator access is required.", 403

    if request.method not in ("GET", "HEAD"):
        if request.headers.get("Origin") != settings.origin:
            return "bad-request-origin", "The request origin is invalid.", 403
        opened_as = request.headers.get("X-MarcEdit-Request")
        if not opened_as:
            return "bad-request-origin", "The browser verification header is missing.", 403
        if opened_as != access.email:
            return "identity-changed", "Your signed-in identity has changed.", 409

    return None
