import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import InMemorySession, get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def generate_user_code() -> str:
    import random
    import string
    from datetime import datetime

    year = datetime.now().year
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"PH-{year}-{suffix}"


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession | InMemorySession = Depends(get_db)) -> UserOut:
    if isinstance(db, InMemorySession):
        existing = next((user for user in db.objects if getattr(user, "email", None) == str(payload.email)), None)
        if existing:
            raise HTTPException(status_code=400, detail="El correo ya está registrado")

        user = User(
            email=str(payload.email),
            hashed_password=get_password_hash(payload.password),
            full_name=payload.full_name,
            user_code=generate_user_code(),
            role="free",
        )
        user.id = str(uuid.uuid4())
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return UserOut.model_validate(user)

    existing = await db.scalar(select(User).where(User.email == str(payload.email)))
    if existing:
        raise HTTPException(status_code=400, detail="El correo ya está registrado")

    user = User(
        email=str(payload.email),
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name,
        user_code=generate_user_code(),
        role="free",
    )
    user.id = str(uuid.uuid4())
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession | InMemorySession = Depends(get_db)) -> TokenResponse:
    if isinstance(db, InMemorySession):
        user = next((user for user in db.objects if getattr(user, "email", None) == str(payload.email)), None)
        if not user or not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        token = create_access_token(subject=str(user.id))
        return TokenResponse(access_token=token)

    user = await db.scalar(select(User).where(User.email == str(payload.email)))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token() -> TokenResponse:
    token = create_access_token(subject="refresh-user")
    return TokenResponse(access_token=token)


@router.post("/admin-login", response_model=TokenResponse)
def admin_login(body: dict[str, Any] = Body(...)) -> TokenResponse:
    """Login del panel interno — valida contra ADMIN_USER / ADMIN_PASSWORD del .env."""
    settings = get_settings()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if (
        not settings.admin_password
        or username != settings.admin_user
        or password != settings.admin_password
    ):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    token = create_access_token(subject="admin", role="superadmin")
    return TokenResponse(access_token=token)


@router.post("/forgot-password")
async def forgot_password(email: str) -> dict[str, str]:
    return {"message": f"Si el correo {email} existe, enviaremos instrucciones para restablecer la contraseña"}


@router.post("/reset-password")
async def reset_password() -> dict[str, str]:
    return {"message": "La contraseña ha sido restablecida correctamente"}
