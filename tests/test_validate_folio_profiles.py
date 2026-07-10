from __future__ import annotations

from marcedit_web.lib import folio_profiles
from marcedit_web.lib.rules import RuleSet
from marcedit_web.render import validate


class _FakeStatus:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, **_kwargs):
        return None


class _FakeStore:
    def __init__(self, records):
        self._records = records

    def iter_records(self):
        return iter(self._records)


def test_compute_issues_includes_selected_folio_profile(make_record, monkeypatch):
    """Validate includes selected FOLIO profile diagnostics in its issue list."""
    monkeypatch.setattr(validate.st, "status", lambda *_args, **_kwargs: _FakeStatus())
    monkeypatch.setattr(
        validate.folio_profiles,
        "rules_for_profile",
        lambda profile_key, include_addons=(): [
            rule
            for rule in folio_profiles.default_rules_for_tests()
            if rule.key == "folio-new-load-forbidden-001"
        ],
    )
    store = _FakeStore([make_record()])

    issues = validate._compute_issues(
        RuleSet(),
        store,
        malformed=0,
        folio_context=folio_profiles.FolioContext(profile_key="folio-new-instance"),
    )

    assert "folio-new-load-forbidden-001" in {issue.code for issue in issues}


def test_folio_context_from_state_uses_selected_profile(monkeypatch):
    """Validate can build FOLIO context from selected Streamlit state values."""
    monkeypatch.setattr(
        validate.st,
        "session_state",
        {
            "folio_profile_key": "folio-new-instance",
            "folio_profile_addons": ["folio-ecollection-ebook"],
            "folio_container_code": "FC-ABC",
            "folio_institution_suffix": "SC",
            "folio_collection_name": "Five Colleges collection",
            "folio_score_loading": True,
            "folio_use_949": True,
            "folio_multi_institution": True,
        },
    )

    context = validate._folio_context_from_state()

    assert context == folio_profiles.FolioContext(
        profile_key="folio-new-instance",
        addons=("folio-ecollection-ebook",),
        container_code="FC-ABC",
        institution_suffix="SC",
        collection_name="Five Colleges collection",
        score_loading=True,
        use_949=True,
        multi_institution=True,
    )


def test_build_folio_context_includes_ebook_addon():
    """Validate UI helper converts selected controls into evaluator context."""
    context = validate._build_folio_context(
        profile_key="folio-new-instance",
        addon_enabled=True,
        institution_suffix="SC",
        container_code="FC123",
        score_loading=False,
    )

    assert context.profile_key == "folio-new-instance"
    assert context.addons == ("folio-ecollection-ebook",)
    assert context.institution_suffix == "SC"
    assert context.container_code == "FC123"


def test_build_folio_context_disabled_when_profile_blank():
    """Leaving the profile blank keeps Validate behavior unchanged."""
    assert validate._build_folio_context(
        profile_key="",
        addon_enabled=True,
        institution_suffix="SC",
        container_code="FC123",
        score_loading=False,
    ) is None
