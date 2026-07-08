from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "PriceHunter Pro"
    secret_key: str = "change-me"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://user:pass@postgres:5432/pricehunter"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    telegram_bot_token: str = ""
    telegram_admin_id: str = ""
    telegram_channel_dev: str = ""
    telegram_channel_prd: str = ""
    admin_user: str = "admin"
    admin_password: str = ""

    @property
    def telegram_channel(self) -> str:
        if self.environment == "production" and self.telegram_channel_prd:
            return self.telegram_channel_prd
        return self.telegram_channel_dev

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
