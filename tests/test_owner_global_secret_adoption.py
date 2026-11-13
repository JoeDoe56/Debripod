from __future__ import annotations

from debripod import settings


def _fake_store(monkeypatch, initial):
    store = dict(initial)

    def saved_status(user_id):
        return {service: {"saved": True} for (scope, service), value in store.items() if scope == user_id and value}

    def get_secret(user_id, service):
        return store.get((user_id, service), "")

    def set_secret(user_id, service, value, **_kwargs):
        store[(user_id, service)] = value

    monkeypatch.setattr(settings, "saved_status", saved_status)
    monkeypatch.setattr(settings, "get_secret", get_secret)
    monkeypatch.setattr(settings, "set_secret", set_secret)
    return store


def test_owner_inherits_legacy_global_soulseek_credentials(monkeypatch):
    store = _fake_store(monkeypatch, {
        ("global", "SOULSEEK_USERNAME"): "slsk-user",
        ("global", "SOULSEEK_PASSWORD"): "slsk-pass",
    })
    adopted = settings.adopt_global_secrets_for_owner("owner1")
    assert sorted(adopted) == ["SOULSEEK_PASSWORD", "SOULSEEK_USERNAME"]
    assert store[("owner1", "SOULSEEK_USERNAME")] == "slsk-user"
    assert store[("owner1", "SOULSEEK_PASSWORD")] == "slsk-pass"
    # The legacy copy is kept.
    assert store[("global", "SOULSEEK_PASSWORD")] == "slsk-pass"


def test_owner_own_credentials_are_never_overwritten(monkeypatch):
    store = _fake_store(monkeypatch, {
        ("global", "SOULSEEK_USERNAME"): "old-user",
        ("global", "SOULSEEK_PASSWORD"): "old-pass",
        ("owner1", "SOULSEEK_USERNAME"): "new-user",
        ("owner1", "SOULSEEK_PASSWORD"): "new-pass",
    })
    assert settings.adopt_global_secrets_for_owner("owner1") == []
    assert store[("owner1", "SOULSEEK_USERNAME")] == "new-user"
    assert store[("owner1", "SOULSEEK_PASSWORD")] == "new-pass"


def test_nothing_to_adopt_without_global_credentials(monkeypatch):
    store = _fake_store(monkeypatch, {})
    assert settings.adopt_global_secrets_for_owner("owner1") == []
    assert store == {}
