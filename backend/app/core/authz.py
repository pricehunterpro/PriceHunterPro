"""Autorizacion de escrituras.

Antes de esto el JWT llevaba un campo `role` que NADIE comprobaba: cualquier
POST/PUT/PATCH/DELETE contra la API se ejecutaba sin token. El "modo admin"
existia solo en el frontend, asi que bastaba con llamar a la API a mano.

La comprobacion se hace en un unico middleware en vez de repartir 72
`Depends(...)` por los routers: asi un endpoint nuevo nace protegido por
defecto y no depende de que alguien se acuerde de anotarlo.

Reglas:
  * GET/HEAD/OPTIONS            -> abiertos (la vista de ofertas es publica).
  * /api/v1/auth/*              -> abiertos (son los que entregan el token).
  * /api/v1/watchlist*          -> requieren sesion valida (cualquier rol).
  * cualquier otra escritura    -> requiere rol admin o superadmin.
"""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.security import decode_token

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
ADMIN_ROLES = frozenset({"admin", "superadmin"})

# Escrituras que no exigen token: son las que lo entregan.
PUBLIC_WRITE_PREFIXES = ("/api/v1/auth/",)

# Escrituras de usuario final: basta con estar autenticado.
AUTHENTICATED_WRITE_PREFIXES = ("/api/v1/watchlist",)


def _unauthorized(detail: str, status_code: int) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(status_code=status_code, content={"detail": detail}, headers=headers)


def _claims(request: Request) -> dict[str, Any] | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    try:
        return decode_token(token.strip())
    except Exception:  # token invalido, expirado o malformado
        return None


async def enforce_write_authorization(request: Request, call_next: Any) -> Any:
    path = request.url.path

    if request.method in SAFE_METHODS:
        return await call_next(request)
    if not path.startswith("/api/"):
        return await call_next(request)
    if path.startswith(PUBLIC_WRITE_PREFIXES):
        return await call_next(request)

    claims = _claims(request)
    if claims is None:
        return _unauthorized("Se requiere autenticacion", 401)

    if path.startswith(AUTHENTICATED_WRITE_PREFIXES):
        return await call_next(request)

    if str(claims.get("role", "")).lower() not in ADMIN_ROLES:
        return _unauthorized("Se requiere rol de administrador", 403)

    request.state.principal = claims
    return await call_next(request)
