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

    assert "from marcedit_web.lib.product_identity import PRODUCT_NAME" in app
    assert "page_title=PRODUCT_NAME" in app

    assert "from marcedit_web.lib.product_identity import PRODUCT_NAME" in home
    assert "st.title(PRODUCT_NAME)" in home
    assert "st.header(PRODUCT_NAME)" in home

    assert "from marcedit_web.lib.product_identity import PRODUCT_NAME" in diff
    assert "st.header(PRODUCT_NAME)" in diff


def test_current_streamlit_brand_calls_do_not_embed_legacy_name():
    app = _source("marcedit_web/App.py")
    home = _source("marcedit_web/views/00_Home.py")
    diff = _source("marcedit_web/views/6_Diff.py")

    assert 'page_title="marcedit-web"' not in app
    assert 'st.title("marcedit-web")' not in home
    assert 'st.header("marcedit-web")' not in home
    assert 'st.header("marcedit-web")' not in diff
