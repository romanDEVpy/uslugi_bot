import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: List[int] = []

    # Database
    DATABASE_URL: str  # e.g. postgresql+asyncpg://bot:secret@localhost:5432/gosuslugi_bot

    # CryptoBot
    CRYPTOBOT_TOKEN: str = ""
    CRYPTOBOT_NETWORK: str = "TEST_NET"  # TEST_NET or MAIN_NET

    # Auth Server & Web Site Hosting
    AUTH_SERVER_URL: str = "http://localhost:8081"
    SITE_BASE_URL: str = "http://localhost:8081/view"

    # Prices in Stars (XTR)
    STARS_PRICE_DAY: int = 50
    STARS_PRICE_WEEK: int = 200
    STARS_PRICE_MONTH: int = 500

    # Prices in USD/fiat for CryptoBot (which supports fiat conversion)
    CRYPTO_PRICE_DAY: float = 1.0
    CRYPTO_PRICE_WEEK: float = 3.0
    CRYPTO_PRICE_MONTH: float = 8.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

settings = Settings()
