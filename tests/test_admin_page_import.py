"""Admin page guard (TASK-088)."""
from __future__ import annotations

import importlib


def test_admin_page_module_imports():
    mod = importlib.import_module("marcedit_web.views.A_Admin")
    assert hasattr(mod, "is_admin")


def test_is_admin_reads_role():
    from marcedit_web.views import A_Admin
    assert A_Admin.is_admin({"role": "admin"}) is True
    assert A_Admin.is_admin({"role": "cataloger"}) is False
    assert A_Admin.is_admin({}) is False
