import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class AuthServerSettings(BaseSettings):
    AUTH_SERVER_HOST: str = "0.0.0.0"
    AUTH_SERVER_PORT: int = 8081
    
    # Database
    DATABASE_URL: str
    
    # Telegram Bot Token (used to notify user when generation succeeds/fails)
    BOT_TOKEN: str
    
    # List of admin telegram IDs
    ADMIN_IDS: str = ""
    
    # Public base URL for site view
    SITE_BASE_URL: str = "http://localhost:8081/view"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

auth_settings = AuthServerSettings()
