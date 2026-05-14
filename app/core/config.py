from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Telegram
    bot_token: str
    moderation_chat_id: int | None = None

    # Channels (only world + economy required now)
    channel_world_id: int
    channel_economy_id: int

    # Legacy channels (kept for compatibility)
    channel_russia_id: int | None = None
    channel_geo_id: int | None = None
    channel_war_id: int | None = None

    # Database
    database_url: str
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "newsbot"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # LLM
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"
    llm_rewrite_enabled: bool = True
    llm_timeout_seconds: int = 90

    # Pipeline
    pipeline_interval_minutes: int = 15
    max_posts_per_run: int = 15
    max_posts_per_channel: int = 6

    # Quality
    min_quality_score: int = 4
    min_trust_score: float = 0.45
    auto_publish_confidence_threshold: float = 0.55

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
