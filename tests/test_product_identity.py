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
