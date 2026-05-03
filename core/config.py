from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""
    database_url: str = ""

    # Gemini
    gemini_api_key: str = ""

    # Service URLs
    email_marketing_url: str = "http://localhost:8004"
    b2b_prospector_url: str = "http://localhost:8000"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Widget CDN base URL (where widget.js is served from)
    widget_base_url: str = "http://localhost:8005"

    # Service
    environment: str = "development"
    log_level: str = "INFO"
    ai_chatbot_url: str = "http://localhost:8005"

    # CORS origins for widget (allow all in dev, restrict in prod)
    allowed_origins: str = "*"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
