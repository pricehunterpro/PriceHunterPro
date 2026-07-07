from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models import Base

settings = get_settings()

# Hosts locales que NO usan SSL (Postgres de Docker/dev). Cualquier otro host
# (p. ej. el pooler de Supabase) requiere conexión cifrada.
_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "postgres", "db", ""}


def _connect_args(url: str) -> dict:
    host = urlsplit(url).hostname or ""
    if host in _LOCAL_DB_HOSTS:
        return {}
    # asyncpg: 'require' cifra la conexión (equivalente a sslmode=require)
    return {"ssl": "require"}

engine = None
AsyncSessionLocal = None


class InMemorySession:
    def __init__(self) -> None:
        self.objects: list[object] = []

    def add(self, obj: object) -> None:
        self.objects.append(obj)

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: object) -> None:
        return None


try:
    engine = create_async_engine(
        settings.database_url,
        echo=settings.environment == "development",
        future=True,
        connect_args=_connect_args(settings.database_url),
    )
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
except ModuleNotFoundError:
    engine = None
    AsyncSessionLocal = None


async def get_db() -> AsyncSession | InMemorySession:
    if AsyncSessionLocal is None:
        yield InMemorySession()
        return
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    if engine is None:
        raise RuntimeError("El motor de base de datos no está inicializado")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
