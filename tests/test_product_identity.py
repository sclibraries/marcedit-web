"""Product identity and licensing boundaries for TASK-176."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_NAME = "Smith College Libraries MARC21 workflow application"


def test_interim_product_name_is_neutral_and_centralized():
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


def test_readme_and_package_description_are_independent_and_neutral():
    readme = _source("README.md")
    design = _source(
        "docs/superpowers/specs/"
        "2026-07-29-smith-metadata-studio-open-task-migration-design.md"
    )
    pyproject = _source("pyproject.toml")

    assert readme.startswith(f"# {PRODUCT_NAME}\n")
    assert "Recreates MarcEdit" not in readme
    assert "not affiliated with or endorsed by MarcEdit or its author" in readme
    assert "external MarcEdit task and mnemonic text formats" in " ".join(readme.split())
    assert "external MarcEdit task and mnemonic text formats" in " ".join(design.split())
    assert "recreating MarcEdit" not in pyproject
    assert 'description = "Independent web application for MARC21 metadata workflows."' in pyproject


def test_user_facing_editor_copy_uses_neutral_record_editor_label():
    """Application labels must not turn an external format name into a brand."""
    editor_page = _source("marcedit_web/views/5_MarcEditor.py")
    editor_render = _source("marcedit_web/render/edit.py")
    home = _source("marcedit_web/views/00_Home.py")
    readme = _source("README.md")

    assert 'st.title("Record Editor")' in editor_page
    assert 'session.require_upload("edit records in Record Editor")' in editor_render
    assert '"Record Editor mode"' in editor_render
    assert "Record Editor / Tasks / Quick find/replace" in home
    assert "streamlit-ace (for the Record Editor page)" in readme

    assert 'st.title("MarcEditor")' not in editor_page
    assert '"MarcEditor mode"' not in editor_render
    assert "MarcEditor / Tasks / Quick find/replace" not in home


def test_existing_technical_identifiers_remain_compatible():
    readme = _source("README.md")
    pyproject = _source("pyproject.toml")

    assert 'name = "marcedit-web"' in pyproject
    assert "https://libtools2.smith.edu/marcedit-web/" in readme
    assert "streamlit run marcedit_web/App.py" in readme


def test_docker_image_includes_project_license_and_notices():
    dockerfile = _source("Dockerfile")

    assert "COPY LICENSE THIRD_PARTY_NOTICES.md ./" in dockerfile


def test_docker_dependency_install_precedes_changeable_license_copy():
    dockerfile = _source("Dockerfile")

    # Ranged requirements must remain behind a reusable layer when only
    # project licensing text changes, avoiding an unintended re-resolution.
    assert dockerfile.index("RUN pip install -r requirements.txt") < dockerfile.index(
        "COPY LICENSE THIRD_PARTY_NOTICES.md ./"
    )
