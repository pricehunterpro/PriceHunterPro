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
    test_user: str = ""
    test_password: str = ""
    test2_user: str = ""
    test2_password: str = ""
    # Origenes permitidos por CORS. En produccion NUNCA debe quedar "*":
    # el frontend llama por el proxy same-origin de Vercel (/api/*).
    cors_origins: str = "https://pricehunter-pro.vercel.app,http://localhost:4200"

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def telegram_channel(self) -> str:
        if self.environment == "production" and self.telegram_channel_prd:
            return self.telegram_channel_prd
        return self.telegram_channel_dev

    class Config:
        env_file = ".env"
        case_sensitive = False


INSECURE_DEFAULTS = {"change-me", "", "secret", "changeme"}


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    # Un JWT_SECRET_KEY por defecto en produccion permite a cualquiera firmar
    # un token con role=superadmin. Preferimos no arrancar antes que arrancar
    # con la puerta abierta.
    if settings.is_production and settings.jwt_secret_key in INSECURE_DEFAULTS:
        raise RuntimeError(
            "JWT_SECRET_KEY no esta configurado (o usa el valor por defecto) "
            "con ENVIRONMENT=production. Define un secreto aleatorio antes de arrancar."
        )
    if settings.is_production and "*" in settings.allowed_origins:
        raise RuntimeError("CORS_ORIGINS no puede ser '*' con ENVIRONMENT=production.")
    return settings
