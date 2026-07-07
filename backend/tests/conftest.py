"""Configuración de pytest.

Los endpoints que dependen de `get_db` (auth, watchlist, ...) tienen ramas
dedicadas para `InMemorySession`, pensadas para ejecutar la suite sin una base
de datos real (p. ej. en CI). Ese modo solo se activaba de forma automática
cuando faltaba el driver; aquí lo forzamos sobrescribiendo la dependencia
`get_db`, de modo que los tests corran de forma determinista y sin red.

Los servicios de deals/products usan su propio engine síncrono y ya caen a
datos de ejemplo si la BD no está disponible, por lo que no requieren override.
"""
from collections.abc import Iterator

from app.core.database import InMemorySession, get_db
from app.main import app


def _inmemory_db() -> Iterator[InMemorySession]:
    yield InMemorySession()


app.dependency_overrides[get_db] = _inmemory_db
