"""Selección de ofertas estilo SUPERCUPON.

Reemplaza el viejo ranking `descuento% × ahorro_en_soles` que solo sacaba
productos caros (S/1500–5000). El gancho de los canales virales es siempre:

    [Producto deseable]  a  [precio final atractivo]

…con VARIEDAD de precio (desde lo barato de impulso hasta 1–2 premium) y las
marcas que la gente reconoce (Apple, Samsung, Adidas, PS5, LG, Sony…). Este
módulo centraliza esa lógica para que la usen los 3 publicadores:
    - publish_top_deals   (top-5 gangas 3×/día → Telegram)
    - Publicador IA        (top-16 del panel)
    - _notify_new_alerts   (alertas en tiempo real; usa solo el filtro de basura)
"""
from __future__ import annotations

import re
from typing import Any, Iterable

def _regex_deseables() -> str:
    """Regex POSIX con LÍMITES DE PALABRA (\\y de Postgres) que empareja cualquier
    marca/keyword deseable. Se deriva del MISMO set que `marca_es_deseable` para no
    duplicar la lista. Las keywords son [a-z0-9 ], no requieren escape en ARE."""
    alternativas = "|".join(k.strip() for k in sorted(MARCAS_DESEABLES) if k.strip())
    return r"\y(" + alternativas + r")\y"


# SQL: pool de candidatos limpio, con TODOS los tramos y con las marcas DESEABLES
# priorizadas dentro de cada tramo (deseable DESC, disc DESC). Así los productos
# reconocibles entran al pool aunque su descuento sea menor que el de un genérico
# con original inflado.
# - Deduplica por nombre (la tienda más barata de cada producto).
# - Guards anti-basura de parsing (original corrupto = millones / ratios absurdos).
# NOTA: los glitches extremos "a 1 sol" NO salen por acá (el guard *10 los corta);
#       esos van por _notify_new_alerts, que los valida con la mediana histórica.
_SQL_CANDIDATOS = """
    WITH base AS (
        SELECT DISTINCT ON (lower(btrim(p.name)))
               p.id, p.name, sp.store,
               COALESCE(NULLIF(p.category, ''), 'General') AS category,
               COALESCE(p.brand, '')                       AS brand,
               COALESCE(p.image_url, '')                   AS image_url,
               CAST(sp.current_price  AS float)            AS current_price,
               CAST(sp.original_price AS float)            AS original_price,
               CAST((sp.original_price - sp.current_price)
                    / sp.original_price * 100 AS float)     AS disc,
               sp.url,
               ((lower(p.name) || ' ' || lower(COALESCE(p.brand, ''))) ~ :re_des) AS deseable,
               CASE WHEN sp.current_price < 100 THEN 'barato'
                    WHEN sp.current_price < 300 THEN 'impulso'
                    WHEN sp.current_price < 1000 THEN 'medio'
                    ELSE 'premium' END                      AS tramo
        FROM store_products sp
        JOIN products p ON p.id = sp.product_id
        WHERE sp.in_stock = true
          AND sp.original_price > sp.current_price
          AND sp.current_price  > 0
          AND sp.original_price >= 60                        -- original mínimo
          AND (sp.original_price - sp.current_price) >= 30   -- ahorro real >= S/30
          AND sp.original_price < 100000                     -- guard parsing corrupto
          AND sp.original_price < sp.current_price * 10      -- descarta ratios absurdos
          AND (sp.original_price - sp.current_price) / sp.original_price >= 0.40
        ORDER BY lower(btrim(p.name)), sp.current_price ASC
    ),
    ranked AS (
        SELECT *, ROW_NUMBER() OVER (
                   PARTITION BY tramo ORDER BY deseable DESC, disc DESC
               ) AS rn_tramo
        FROM base
    )
    SELECT id, name, store, category, brand, image_url,
           current_price, original_price, disc, url, deseable
    FROM ranked
    WHERE rn_tramo <= 200
"""


def fetch_candidates(session) -> list[dict[str, Any]]:
    """Trae el pool de candidatos (todos los tramos) listo para `seleccionar_top`."""
    from sqlalchemy import text
    rows = session.execute(text(_SQL_CANDIDATOS), {"re_des": _regex_deseables()}).fetchall()
    return [
        {
            "id":            r.id,
            "name":          r.name,
            "store":         r.store,
            "category":      r.category,
            "brand":         r.brand,
            "imageUrl":      r.image_url,
            "currentPrice":  r.current_price,
            "originalPrice": r.original_price,
            "discountPct":   r.disc,
            "url":           r.url,
        }
        for r in rows
    ]

# ── Marcas / keywords DESEABLES (boost). Se buscan dentro de "nombre + marca". ──
MARCAS_DESEABLES: set[str] = {
    # Apple / móviles
    "apple", "iphone", "ipad", "macbook", "airpods", "apple watch",
    "samsung", "galaxy", "xiaomi", "redmi", "motorola", "moto",
    "huawei", "honor", "oppo", "realme", "nokia",
    # Audio / TV / hogar tech
    "lg", "sony", "jbl", "bose", "panasonic", "philips", "tcl", "hisense",
    "jvc", "harman", "marshall",
    # Gaming
    "playstation", "ps5", "ps4", "nintendo", "xbox",
    # Cómputo
    "lenovo", "ideapad", "thinkpad", "hp", "pavilion", "dell", "acer",
    "asus", "rog", "msi", "logitech", "razer", "hyperx",
    # Moda / deporte
    "adidas", "nike", "puma", "reebok", "under armour", "new balance",
    "vans", "converse", "fila", "north face",
    # Electrodomésticos
    "electrolux", "bosch", "indurama", "mabe", "midea", "whirlpool",
    "oster", "imaco", "dyson", "coldex",
    # Foto / drones
    "canon", "nikon", "gopro", "dji",
    # Juguetes deseables
    "lego", "hot wheels", "barbie", "nerf", "mario kart",
}

# ── Marcas basura (revendedores sin nombre) → se descartan salvo que el nombre
#    contenga una marca deseable. Detectadas en el análisis del pool real. ──
MARCAS_BASURA: set[str] = {
    "generico", "genericos", "generic", "sin marca", "tu mesita",
    "rybiu import", "rybiu", "other f f", "alto hogar", "dermo sumak",
    "universe nutrition", "kaz home", "importaciones",
}

# ── Categorías spam que copaban el top por descuento corrupto (p.ej. Lentes
#    Invicta casi idénticos). ──
CATEGORIAS_BLOQUEADAS: set[str] = {"lentes"}


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


# Regex con LÍMITES DE PALABRA: evita que "lg" empareje "co(lg)ante" o "hp" caiga
# dentro de otra palabra. Se compila una vez desde el set.
_RE_DESEABLES = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(MARCAS_DESEABLES)) + r")\b",
    re.IGNORECASE,
)


def marca_es_deseable(name: Any, brand: Any) -> bool:
    hay = _norm(name) + " " + _norm(brand)
    return bool(_RE_DESEABLES.search(hay))


def es_basura(name: Any, brand: Any, category: Any) -> bool:
    """True si la oferta es 'basura' (revendedor genérico o categoría spam) y
    NO la salva una marca deseable en el nombre."""
    if _norm(category) in CATEGORIAS_BLOQUEADAS:
        return True
    b = _norm(brand)
    if any(k in b for k in MARCAS_BASURA):
        return not marca_es_deseable(name, brand)
    return False


def _tramo(price: float) -> str:
    if price < 100:
        return "barato"      # eye-catchers de impulso (Adidas 56, sandalias 68)
    if price < 300:
        return "impulso"     # tablet 299, silla 100, mesa 99
    if price < 1000:
        return "medio"       # PS5 879, congeladora 399, laptop 949
    return "premium"         # iPhones, TVs, laptops premium (máx 1-2 por tanda)


# Cupos por tanda según el spread observado en el SUPERCUPON: mayoría alcanzable,
# pocos premium. Si un tramo no llena su cupo, el resto se completa por score.
CUPOS_16 = {"barato": 5, "impulso": 5, "medio": 4, "premium": 2}
CUPOS_5 = {"barato": 2, "impulso": 1, "medio": 1, "premium": 1}


def score(deal: dict[str, Any]) -> float:
    """Puntaje de deseabilidad/viralidad. YA no premia el ahorro en soles (eso
    era lo que empujaba solo lo caro)."""
    disc = float(deal.get("discountPct") or deal.get("disc") or 0)
    s = disc
    price = float(deal.get("currentPrice") or deal.get("current_price") or 0)
    if marca_es_deseable(deal.get("name"), deal.get("brand")):
        s += 25
    if deal.get("priceError"):
        s += 40                       # glitch/precio-error = lo más viral
    # afinidad de precio: lo alcanzable pesa más (curva suave, no un tope duro)
    if price < 100:
        s += 15
    elif price < 300:
        s += 10
    elif price < 1000:
        s += 4
    if disc >= 85:
        s += 15                       # "90% descto" engancha por sí solo
    return s


def seleccionar_top(
    deals: Iterable[dict[str, Any]],
    total: int = 16,
    cupos: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Elige `total` ofertas con VARIEDAD por tramo de precio, priorizando marca
    deseable + descuento + precio alcanzable. Descarta basura y deduplica por
    nombre normalizado."""
    if cupos is None:
        cupos = CUPOS_16 if total >= 16 else CUPOS_5

    limpio: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for d in deals:
        if es_basura(d.get("name"), d.get("brand"), d.get("category")):
            continue
        clave = _norm(d.get("name"))
        if clave and clave in vistos:
            continue
        vistos.add(clave)
        d = dict(d)
        d["_deseable"] = marca_es_deseable(d.get("name"), d.get("brand"))
        d["_score"] = score(d)
        d["_tramo"] = _tramo(float(d.get("currentPrice") or d.get("current_price") or 0))
        limpio.append(d)

    # Marcas DESEABLES primero (como el SUPERCUPON: casi todo es marca reconocible);
    # dentro de cada grupo, por score. Así lo genérico solo rellena vacantes.
    limpio.sort(key=lambda x: (not x["_deseable"], -x["_score"]))

    seleccion: list[dict[str, Any]] = []
    por_tramo = {t: 0 for t in ("barato", "impulso", "medio", "premium")}
    # 1ª pasada: solo DESEABLES, respetando cupos por tramo (variedad garantizada)
    for d in limpio:
        t = d["_tramo"]
        if d["_deseable"] and por_tramo[t] < cupos.get(t, 0) and len(seleccion) < total:
            seleccion.append(d)
            por_tramo[t] += 1
    # 2ª pasada: completa cupos de tramo con lo mejor que quede (deseable o no)
    ya = {id(d) for d in seleccion}
    for d in limpio:
        t = d["_tramo"]
        if id(d) not in ya and por_tramo[t] < cupos.get(t, 0) and len(seleccion) < total:
            seleccion.append(d)
            ya.add(id(d))
            por_tramo[t] += 1
    # 3ª pasada: si aún faltan vacantes (algún tramo sin stock), completa por score
    if len(seleccion) < total:
        for d in limpio:
            if id(d) not in ya:
                seleccion.append(d)
                ya.add(id(d))
                if len(seleccion) >= total:
                    break

    seleccion.sort(key=lambda x: (not x["_deseable"], -x["_score"]))
    return seleccion[:total]


# ── Copy estilo SUPERCUPON: el TITULAR es el precio final, no el "%". ──

def titular(name: Any, current: float, disc: float = 0, price_error: bool = False) -> str:
    corto = str(name or "").strip()
    corto = corto[:50] + ("…" if len(corto) > 50 else "")
    if price_error or current <= 5:
        return f"🚨 {corto} ¡a solo S/ {current:.2f}!"
    if current < 1000:
        return f"🔥 {corto} a solo S/ {current:.0f}"
    return f"🔥 {corto} a S/ {current:,.0f}"
