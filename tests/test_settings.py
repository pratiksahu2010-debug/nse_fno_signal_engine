from config.settings import Settings

def test_defaults_are_signal_only(monkeypatch):
    for key in ["MIN_SCORE", "EXPLOSION_MIN_SCORE", "ENTRY_MODE", "FILTER_PROFILE", "DB_BACKEND", "SIGNAL_ONLY"]:
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env()
    assert settings.min_score == 80
    assert settings.explosion_min_score == 80
    assert settings.entry_mode == "close"
    assert settings.filter_profile == "strict"
    assert settings.db_backend == "memory"
    assert settings.signal_only is True

def test_invalid_min_score_rejected(monkeypatch):
    monkeypatch.setenv("MIN_SCORE", "64")
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "MIN_SCORE" in str(exc)
    else:
        raise AssertionError("Expected invalid MIN_SCORE to raise")

def test_invalid_filter_profile_rejected(monkeypatch):
    monkeypatch.setenv("FILTER_PROFILE", "aggressive-ish")
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "FILTER_PROFILE" in str(exc)
    else:
        raise AssertionError("Expected invalid FILTER_PROFILE to raise")
