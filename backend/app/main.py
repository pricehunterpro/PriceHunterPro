from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.ai import router as ai_router
from app.api.v1.ai_trends import router as ai_trends_router
from app.api.v1.bi_analytics import router as bi_analytics_router
from app.api.v1.bi_profitability import router as bi_profitability_router
from app.api.v1.bi_portfolio import router as bi_portfolio_router
from app.api.v1.bi_top_products import router as bi_top_products_router
from app.api.v1.templates import router as templates_router
from app.api.v1.scrapers import router as scrapers_router
from app.api.v1.processes import router as processes_router
from app.api.v1.logs import router as logs_router
from app.api.v1.history import router as history_router
from app.api.v1.users import router as users_router
from app.api.v1.auth import router as auth_router
from app.api.v1.deals import router as deals_router
from app.api.v1.monitoring import router as monitoring_router
from app.api.v1.tiktok import router as tiktok_router
from app.api.v1.supervision import router as supervision_router
from app.api.v1.publicador import router as publicador_router
from app.api.v1.products import router as products_router
from app.api.v1.watchlist import router as watchlist_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai_router,          prefix="/api/v1")
app.include_router(ai_trends_router,   prefix="/api/v1")
app.include_router(bi_analytics_router, prefix="/api/v1")
app.include_router(bi_profitability_router, prefix="/api/v1")
app.include_router(bi_portfolio_router, prefix="/api/v1")
app.include_router(bi_top_products_router, prefix="/api/v1")
app.include_router(templates_router,   prefix="/api/v1")
app.include_router(scrapers_router,    prefix="/api/v1")
app.include_router(processes_router,   prefix="/api/v1")
app.include_router(logs_router,        prefix="/api/v1")
app.include_router(history_router,     prefix="/api/v1")
app.include_router(users_router,       prefix="/api/v1")
app.include_router(auth_router,        prefix="/api/v1")
app.include_router(deals_router,       prefix="/api/v1")
app.include_router(monitoring_router,  prefix="/api/v1")
app.include_router(tiktok_router,      prefix="/api/v1")
app.include_router(supervision_router, prefix="/api/v1")
app.include_router(publicador_router,  prefix="/api/v1")
app.include_router(products_router,    prefix="/api/v1")
app.include_router(watchlist_router,   prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
