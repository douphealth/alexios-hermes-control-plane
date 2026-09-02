from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8080

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "alexios-hermes-control-plane"
    max_concurrent_activities: int = Field(default=6, ge=1, le=24)
    database_url: str = "postgresql://postgres:postgres@localhost:5432/hermes_control_plane"
    portfolio_sites_json: str | None = None

    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    telegram_allowed_user_ids: str = ""

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_luna_model: str = "gpt-5.6-luna"
    openai_luna_reasoning: str = "low"
    openai_terra_model: str = "gpt-5.6-terra"
    openai_terra_reasoning: str = "high"
    openai_sol_model: str = "gpt-5.6-sol"
    openai_sol_reasoning: str = "xhigh"

    glm_api_key: str | None = None
    glm_base_url: str | None = None
    glm_model: str = "glm-5.3"
    glm_flash_api_key: str | None = None
    glm_flash_base_url: str | None = None
    glm_flash_model: str = "glm-5.3-flash"

    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_reasoning: str = "high"

    allow_production_writes: bool = Field(default=False)

    @field_validator("app_env")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return value.strip().lower()

    @property
    def allowed_telegram_users(self) -> set[int]:
        return {int(v.strip()) for v in self.telegram_allowed_user_ids.split(",") if v.strip()}

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def assert_secure_telegram_config(self) -> None:
        if not self.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        if self.is_production and not self.telegram_webhook_secret:
            raise RuntimeError("TELEGRAM_WEBHOOK_SECRET is required in production")
        if self.is_production and not self.allowed_telegram_users:
            raise RuntimeError("TELEGRAM_ALLOWED_USER_IDS must be explicit in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
