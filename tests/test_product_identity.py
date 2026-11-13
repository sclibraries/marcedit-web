"""Product identity and licensing boundaries for TASK-176."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_NAME = "Smith Metadata Studio"


def test_approved_product_name_is_centralized():
    from marcedit_web.lib import product_identity

    assert product_identity.PRODUCT_NAME == PRODUCT_NAME
    assert "MarcEdit" not in product_identity.PRODUCT_NAME


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_current_streamlit_brand_surfaces_use_product_name_constant():
    app = _source("marcedit_web/App.py")
    home = _source("marcedit_web/views/00_Home.py")
    diff = _source("marcedit_web/views/6_Diff.py")
    shared_render = _source("marcedit_web/render/__init__.py")

    assert "from marcedit_web.lib.product_identity import PRODUCT_NAME" in app
    assert "page_title=PRODUCT_NAME" in app

    assert "from marcedit_web.lib.product_identity import PRODUCT_NAME" in home
    assert "st.title(PRODUCT_NAME)" in home
    assert "st.header(PRODUCT_NAME)" in home

    assert "from marcedit_web.lib.product_identity import PRODUCT_NAME" in diff
    assert "st.header(PRODUCT_NAME)" in diff

    assert "from marcedit_web.lib.product_identity import PRODUCT_NAME" in shared_render
    assert "st.header(PRODUCT_NAME)" in shared_render


def test_current_streamlit_brand_calls_do_not_embed_legacy_name():
    app = _source("marcedit_web/App.py")
    home = _source("marcedit_web/views/00_Home.py")
    diff = _source("marcedit_web/views/6_Diff.py")
    shared_render = _source("marcedit_web/render/__init__.py")

    assert 'page_title="marcedit-web"' not in app
    assert 'st.title("marcedit-web")' not in home
    assert 'st.header("marcedit-web")' not in home
    assert 'st.header("marcedit-web")' not in diff
    assert 'st.header("marcedit-web")' not in shared_render


def test_repository_has_smith_mit_license():
    license_text = _source("LICENSE")

    assert license_text.startswith("MIT License\n")
    assert "Copyright (c) 2026 Smith College" in license_text
    assert "Permission is hereby granted, free of charge" in license_text


def test_direct_runtime_dependency_notices_are_present():
    notices = _source("THIRD_PARTY_NOTICES.md")
    requirements = _source("requirements.txt")
    expected = {
        "Streamlit": "Apache-2.0",
        "pymarc": "BSD-2-Clause",
        "streamlit-ace": "MIT",
        "Authlib": "BSD-3-Clause",
        "pytest": "MIT",
        "jsonschema": "MIT",
    }

    for project, license_id in expected.items():
        assert project in notices
        assert license_id in notices

    normalized_notices = " ".join(notices.split())
    assert (
        "direct dependencies installed into the application Docker image"
        in normalized_notices
    )
    declared = {
        re.match(r"[A-Za-z0-9_.-]+", line).group(0)
        for raw_line in requirements.splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    }
    assert {name.lower() for name in declared} == {
        name.lower() for name in expected
    }
