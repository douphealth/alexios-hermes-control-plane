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

    gsc_service_account_file: str | None = None
    gsc_lookback_days: int = Field(default=28, ge=7, le=90)
    gsc_row_limit: int = Field(default=250, ge=25, le=25000)
    gsc_max_sites_per_run: int = Field(default=12, ge=1, le=50)

    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    telegram_allowed_user_ids: str = ""
    autonomous_notification_chat_id: int | None = None

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

    autonomous_growth_enabled: bool = False
    autonomous_growth_interval_hours: int = Field(default=24, ge=1, le=168)
    autonomous_growth_mode: str = "DRAFT"
    autonomous_growth_objective: str = (
        "Improve existing portfolio URLs for organic traffic, SEO, GEO, AEO, AI visibility, "
        "SERP performance, topical authority, user value, and monetization using verified evidence."
    )
    autonomous_max_interventions_per_cycle: int = Field(default=3, ge=1, le=10)
    autonomous_max_mutations_per_site: int = Field(default=1, ge=1, le=5)

    wordpress_sites_json: str | None = None
    wordpress_request_timeout_seconds: float = Field(default=30.0, ge=5.0, le=120.0)
    wordpress_allow_content_updates: bool = True
    wordpress_allow_title_updates: bool = True
    wordpress_allow_status_changes: bool = False
    wordpress_backup_dir: str = "/var/lib/ahcp/backups"

    allow_production_writes: bool = Field(default=False)

    @field_validator("app_env")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("autonomous_growth_mode")
    @classmethod
    def validate_autonomous_mode(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"READ_ONLY", "DRAFT", "STAGING", "PRODUCTION_APPROVED"}:
            raise ValueError("AUTONOMOUS_GROWTH_MODE is invalid")
        return normalized

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

    def assert_autonomous_write_safety(self) -> None:
        production_requested = self.autonomous_growth_mode == "PRODUCTION_APPROVED"
        if production_requested and not self.allow_production_writes:
            raise RuntimeError(
                "Autonomous production mode requires ALLOW_PRODUCTION_WRITES=true"
            )
        if self.autonomous_growth_mode != "READ_ONLY" and not self.wordpress_sites_json:
            raise RuntimeError("WordPress site credentials are required for autonomous write modes")


@lru_cache
def get_settings() -> Settings:
    return Settings()
