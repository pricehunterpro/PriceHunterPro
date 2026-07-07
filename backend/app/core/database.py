from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models import Base

settings = get_settings()

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
    engine = create_async_engine(settings.database_url, echo=settings.environment == "development", future=True)
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
