"""Application configuration using Pydantic settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://localhost/speedfog_racing"

    # Twitch OAuth
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    twitch_redirect_uri: str = "http://localhost:8000/api/auth/callback"

    # App
    secret_key: str = "dev-secret-key-change-in-production"
    base_url: str = "http://localhost:8000"
    websocket_url: str = "ws://localhost:8000"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8000"]

    # Seeds
    seeds_pool_dir: str = "/data/seeds"
    speedfog_path: str = ""  # Path to speedfog repo for seed generation
    zips_output_dir: str = "/data/zips"  # Output directory for generated race zips

    # Server
    log_level: str = "INFO"
    log_json: bool = False


settings = Settings()
