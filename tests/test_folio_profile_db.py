from __future__ import annotations

from marcedit_web.lib import db, folio_profiles


def test_folio_seed_migration_creates_default_profiles_and_rules(tmp_path, monkeypatch):
    """Default FOLIO standards are available after schema initialization."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "folio.db"))
    db.reset_for_tests()
    db.init_schema()

    profiles = {profile.key: profile for profile in folio_profiles.list_profiles()}

    assert set(profiles) >= {
        "folio-new-instance",
        "folio-round-trip",
        "folio-ecollection-ebook",
    }
    assert profiles["folio-ecollection-ebook"].is_addon is True

    new_rules = {
        rule.key: rule
        for rule in folio_profiles.rules_for_profile("folio-new-instance")
    }
    assert "folio-new-load-forbidden-001" in new_rules
    assert new_rules["folio-new-load-forbidden-001"].fix["operation"] == "remove_field"


def test_folio_seed_migration_is_idempotent(tmp_path, monkeypatch):
    """Seeding twice must not duplicate local FOLIO profiles or rules."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "folio.db"))
    db.reset_for_tests()
    db.init_schema()
    db.reset_for_tests()
    db.init_schema()

    profiles = [profile.key for profile in folio_profiles.list_profiles()]
    rules = [
        rule.key for rule in folio_profiles.rules_for_profile("folio-new-instance")
    ]

    assert profiles.count("folio-new-instance") == 1
    assert rules.count("folio-new-load-forbidden-001") == 1


def test_seeded_rule_keys_match_default_rules_by_profile(tmp_path, monkeypatch):
    """SQLite seeds must include every enabled default rule used at runtime."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "folio.db"))
    db.reset_for_tests()
    db.init_schema()

    profile_keys = {
        rule.profile_key for rule in folio_profiles.default_rules_for_tests()
    }
    for profile_key in profile_keys:
        seeded = {
            rule.key for rule in folio_profiles.rules_for_profile(profile_key)
        }
        defaults = {
            rule.key
            for rule in folio_profiles.default_rules_for_tests()
            if rule.profile_key == profile_key and rule.enabled
        }

        assert seeded == defaults


def test_rules_for_profile_can_include_addon_rules(tmp_path, monkeypatch):
    """The ebook add-on layers onto a primary workflow profile."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "folio.db"))
    db.reset_for_tests()
    db.init_schema()

    rules = folio_profiles.rules_for_profile(
        "folio-new-instance",
        include_addons=("folio-ecollection-ebook",),
    )
    keys = {rule.key for rule in rules}

    assert "folio-new-load-forbidden-001" in keys
    assert "folio-ebook-required-655" in keys


def test_rules_for_profile_ignores_disabled_addon_profiles(tmp_path, monkeypatch):
    """Disabled add-ons cannot leak rules through stale selections."""
    monkeypatch.setenv("MARCEDIT_WEB_DB_PATH", str(tmp_path / "folio.db"))
    db.reset_for_tests()
    db.init_schema()

    with db.connect() as conn:
        conn.execute(
            "UPDATE folio_profiles SET enabled = 0"
            " WHERE key = 'folio-ecollection-ebook'"
        )

    rules = folio_profiles.rules_for_profile(
        "folio-new-instance",
        include_addons=("folio-ecollection-ebook",),
    )
    keys = {rule.key for rule in rules}

    assert "folio-new-load-forbidden-001" in keys
    assert "folio-ebook-required-655" not in keys
