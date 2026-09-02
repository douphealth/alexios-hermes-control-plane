import pytest

from alexios_hermes_control_plane.config import Settings


def test_production_writes_disabled_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.allow_production_writes is False


def test_allowed_telegram_users_parsing() -> None:
    settings = Settings(_env_file=None, telegram_allowed_user_ids="1, 2,3")
    assert settings.allowed_telegram_users == {1, 2, 3}


def test_production_telegram_requires_secret_and_allowlist() -> None:
    settings = Settings(_env_file=None, app_env="production", telegram_bot_token="token")
    with pytest.raises(RuntimeError, match="TELEGRAM_WEBHOOK_SECRET"):
        settings.assert_secure_telegram_config()

    settings = Settings(
        _env_file=None,
        app_env="production",
        telegram_bot_token="token",
        telegram_webhook_secret="secret",
    )
    with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_USER_IDS"):
        settings.assert_secure_telegram_config()
