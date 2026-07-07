from fastapi import APIRouter, Depends, HTTPException, status

from app.core.database import InMemorySession, get_db

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("")
async def list_watchlist(db: InMemorySession = Depends(get_db)) -> dict[str, object]:
    if isinstance(db, InMemorySession):
        return {"items": []}
    raise HTTPException(status_code=501, detail="Persistencia aún no habilitada")


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(product_id: str, db: InMemorySession = Depends(get_db)) -> dict[str, object]:
    if isinstance(db, InMemorySession):
        return {"message": "Producto agregado a watchlist", "product_id": product_id}
    raise HTTPException(status_code=501, detail="Persistencia aún no habilitada")
