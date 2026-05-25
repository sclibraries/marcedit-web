"""Smoke test: every lifted module imports cleanly under Python 3.9.

This is the load-bearing test for the Stage 2 backport. If any module
contains Python 3.10+ runtime syntax that slipped through review,
this test catches it before the lib is actually used.
"""

from __future__ import annotations


def test_all_lib_modules_import():
    """Every module in marcedit_web.lib is importable."""
    # Order roughly matches dependency edges.
    from marcedit_web.lib import errors  # noqa: F401
    from marcedit_web.lib import transforms  # noqa: F401
    from marcedit_web.lib import viewer  # noqa: F401
    from marcedit_web.lib import reporting  # noqa: F401
    from marcedit_web.lib import preflight  # noqa: F401
    from marcedit_web.lib import tasks  # noqa: F401
    from marcedit_web.lib import editor  # noqa: F401
    from marcedit_web.lib import task_builder  # noqa: F401
    from marcedit_web.lib import marcedit_import  # noqa: F401
    from marcedit_web.lib import marc_diff  # noqa: F401


def test_top_level_package_imports():
    import marcedit_web

    # Sanity check only — the actual version lives in __init__.py.
    # We pin the shape (semver-ish) rather than a specific value so a
    # version bump doesn't require touching this test every release.
    assert isinstance(marcedit_web.__version__, str)
    assert marcedit_web.__version__.count(".") == 2
