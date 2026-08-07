"""Catálogo declarativo de la configuración de PriceHunter Pro.

Cada ajuste se declara UNA vez acá (categoría, clave, tipo, default, validación)
y de eso salen solos: el formulario del front, la validación del PUT y el seed
inicial en base de datos.

Los DEFAULTS son los valores que hoy están hardcodeados en el código, para que
sembrar la configuración no cambie el comportamiento de nada. La referencia de
cada uno va en `source` para poder rastrearla.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Categorías (orden de las pestañas) ───────────────────────────────────────
CATEGORIAS: list[dict[str, str]] = [
    {"id": "general",      "label": "General",       "icon": "sliders",  "desc": "Identidad, idioma y formato de la plataforma"},
    {"id": "motor_ia",     "label": "Motor IA",      "icon": "cpu",      "desc": "Pesos del PriceHunter Score y umbrales de decisión"},
    {"id": "scrapers",     "label": "Scrapers",      "icon": "download", "desc": "Ritmo, límites y comportamiento del scraping"},
    {"id": "publicaciones","label": "Publicaciones", "icon": "send",     "desc": "Cadencia y aprobación de las publicaciones"},
    {"id": "marketing",    "label": "Marketing",     "icon": "megaphone","desc": "Copy, hashtags y marca por defecto"},
    {"id": "alertas",      "label": "Alertas",       "icon": "bell",     "desc": "Cuándo y por dónde avisar de una oferta"},
    {"id": "seguridad",    "label": "Seguridad",     "icon": "shield",   "desc": "Sesiones, contraseñas y auditoría"},
    {"id": "sistema",      "label": "Sistema",       "icon": "server",   "desc": "Estado del servicio y mantenimiento"},
    {"id": "base_datos",   "label": "Base de Datos", "icon": "database", "desc": "Conexión, tamaño y migraciones"},
    {"id": "integraciones","label": "Integraciones", "icon": "plug",     "desc": "Canales y servicios externos"},
]

TIPOS_VALIDOS = {"text", "textarea", "number", "bool", "select", "color", "time_range", "list", "url"}


@dataclass(frozen=True)
class SettingDef:
    category: str
    key: str
    label: str
    type: str
    default: Any
    description: str = ""
    options: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    # `preparado`: el campo existe y se guarda, pero todavía no hay integración
    # detrás. Se marca para que el front lo muestre deshabilitado y nadie crea
    # que ya funciona.
    preparado: bool = False
    source: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "default": self.default,
            "description": self.description,
            "options": list(self.options),
            "min": self.minimum,
            "max": self.maximum,
            "unit": self.unit,
            "preparado": self.preparado,
        }


def _s(*args, **kwargs) -> SettingDef:
    return SettingDef(*args, **kwargs)


# ── 1. GENERAL ───────────────────────────────────────────────────────────────
_GENERAL = [
    _s("general", "nombre_plataforma", "Nombre de la plataforma", "text", "PriceHunter Pro",
       "Nombre visible en la cabecera, títulos y publicaciones.", source="settings.app_name"),
    _s("general", "descripcion", "Descripción", "textarea",
       "Cazador de ofertas del retail peruano: detecta, puntúa y publica las mejores oportunidades.",
       "Descripción corta usada en metadatos y en el pie de las publicaciones."),
    _s("general", "logo_url", "Logo", "url", "/assets/logo_sidebar_transparente.png",
       "Ruta o URL del logo del sidebar."),
    _s("general", "favicon_url", "Favicon", "url", "/favicon.ico", "Ruta o URL del favicon."),
    _s("general", "version", "Versión", "text", "0.1.0",
       "Versión de la plataforma. Se muestra también en la pestaña Sistema.", source="main.py FastAPI(version=)"),
    _s("general", "idioma", "Idioma", "select", "es-PE", "Idioma de la interfaz.",
       options=("es-PE", "es-ES", "en-US")),
    _s("general", "zona_horaria", "Zona horaria", "select", "America/Lima",
       "Zona horaria para horarios de publicación y reportes.",
       options=("America/Lima", "America/Bogota", "America/Santiago", "America/Mexico_City", "UTC")),
    _s("general", "moneda", "Moneda", "select", "PEN", "Moneda de los precios mostrados.",
       options=("PEN", "USD", "CLP", "COP", "MXN")),
    _s("general", "formato_fecha", "Formato de fecha", "select", "dd/MM/yyyy",
       "Formato de fecha en tablas y reportes.",
       options=("dd/MM/yyyy", "yyyy-MM-dd", "MM/dd/yyyy", "dd-MM-yyyy HH:mm")),
    _s("general", "color_principal", "Color principal", "color", "#00E58F",
       "Verde neón de la identidad PriceHunter Pro.", source="styles.css --accent"),
    _s("general", "color_secundario", "Color secundario", "color", "#6ab0ff",
       "Color de apoyo para gráficos y badges secundarios."),
]

# ── 2. MOTOR IA ──────────────────────────────────────────────────────────────
# Los pesos replican el reparto real de `app/ai/scorer.py` (suman 100):
#   histórico 30 · descuento 25 · margen 20 · stock 10 · categoría 8 · tienda 5
# "tendencia" mapea al bloque de categoría (alta/media rotación) y "popularidad"
# al de tienda confiable, que es como el scorer los usa hoy.
_MOTOR_IA = [
    _s("motor_ia", "peso_descuento", "Peso descuento", "number", 25,
       "Puntos que aporta el % de descuento al PriceHunter Score.",
       minimum=0, maximum=100, unit="pts", source="scorer.py bloque 2"),
    _s("motor_ia", "peso_margen", "Peso margen", "number", 20,
       "Puntos que aporta el margen estimado de reventa.",
       minimum=0, maximum=100, unit="pts", source="scorer.py bloque 3"),
    _s("motor_ia", "peso_historico", "Peso histórico", "number", 30,
       "Puntos por estar debajo de la mediana histórica del propio producto.",
       minimum=0, maximum=100, unit="pts", source="scorer.py bloque 1"),
    _s("motor_ia", "peso_tendencia", "Peso tendencia", "number", 8,
       "Puntos por categoría de alta rotación (tendencia de mercado).",
       minimum=0, maximum=100, unit="pts", source="scorer.py bloque 5"),
    _s("motor_ia", "peso_popularidad", "Peso popularidad", "number", 5,
       "Puntos por tienda verificada / de mayor tráfico.",
       minimum=0, maximum=100, unit="pts", source="scorer.py bloque 6"),
    _s("motor_ia", "score_minimo_ganga", "Score mínimo Ganga Extrema", "number", 95,
       "Score desde el cual una oferta se clasifica como Ganga Extrema.",
       minimum=0, maximum=100, source="scorer.py clasificación"),
    _s("motor_ia", "score_minimo_excelente", "Score mínimo Excelente", "number", 80,
       "Score desde el cual la oferta es Excelente Oferta.",
       minimum=0, maximum=100, source="scorer.py clasificación"),
    _s("motor_ia", "score_minimo_publicar", "Score mínimo para publicar", "number", 60,
       "Score mínimo para que Recomendaciones IA sugiera publicar.",
       minimum=0, maximum=100, source="recommendation_engine._SCORE_PUBLICAR"),
    _s("motor_ia", "score_minimo_alerta", "Score mínimo para alertar", "number", 70,
       "Score mínimo para disparar una alerta a los canales.",
       minimum=0, maximum=100),
    _s("motor_ia", "score_minimo_tiktok", "Score mínimo para TikTok", "number", 75,
       "Score mínimo para proponer un video en TikTok Factory.",
       minimum=0, maximum=100),
]

# ── 3. SCRAPERS ──────────────────────────────────────────────────────────────
_SCRAPERS = [
    _s("scrapers", "frecuencia", "Frecuencia", "select", "Cada hora",
       "Cada cuánto corre el scrape programado.",
       options=("Cada 15 minutos", "Cada 30 minutos", "Cada hora", "Cada 2 horas", "Cada 6 horas", "Manual"),
       source="scrapers.py _default_config"),
    _s("scrapers", "timeout", "Timeout", "number", 30, "Timeout por petición HTTP.",
       minimum=5, maximum=300, unit="s", source="scrapers.py _default_config"),
    _s("scrapers", "delay_paginas", "Delay entre páginas", "number", 0.5,
       "Pausa entre páginas de una misma categoría.",
       minimum=0, maximum=30, unit="s", source="scrapers.py _default_config"),
    _s("scrapers", "max_paginas", "Máximo de páginas", "number", 6,
       "Tope de páginas por categoría.", minimum=1, maximum=100, source="scrapers.py _default_config"),
    _s("scrapers", "max_reintentos", "Máximo de reintentos", "number", 3,
       "Reintentos ante error 5xx o de red.", minimum=0, maximum=10, source="scrapers.py _default_config"),
    _s("scrapers", "headless", "Headless", "bool", True,
       "Ejecutar el navegador sin interfaz (solo scrapers con Playwright).",
       source="scrapers.py _default_config"),
    _s("scrapers", "user_agent", "User Agent", "select", "rotativo",
       "Rotativo usa el pool de `stealth.random_user_agent`.",
       options=("rotativo", "chrome", "firefox", "safari"), source="scrapers/stealth.py"),
    _s("scrapers", "proxy", "Proxy", "text", "",
       "URL del proxy de salida. Vacío = conexión directa.", preparado=True),
    _s("scrapers", "workers", "Workers", "number", 4,
       "Procesos del worker de Celery que atienden el scrape.",
       minimum=1, maximum=32, source="docker-compose celery --concurrency"),
]

# ── 4. PUBLICACIONES ─────────────────────────────────────────────────────────
_PUBLICACIONES = [
    _s("publicaciones", "publicaciones_por_hora", "Publicaciones por hora", "number", 3,
       "Tope de publicaciones que se pueden emitir en una hora.", minimum=1, maximum=60),
    _s("publicaciones", "intervalo_minimo", "Intervalo mínimo", "number", 15,
       "Minutos mínimos entre dos publicaciones seguidas.", minimum=1, maximum=1440, unit="min"),
    _s("publicaciones", "publicar_automaticamente", "Publicar automáticamente", "bool", False,
       "Regla vigente del Publicador IA: nada se publica solo, siempre hay acción manual.",
       source="publicador.py — 'NADA se publica automáticamente'"),
    _s("publicaciones", "requiere_aprobacion", "Requiere aprobación", "bool", True,
       "Obliga a pasar por Aprobado antes de publicar."),
    _s("publicaciones", "horarios_permitidos", "Horarios permitidos", "time_range", "09:00-22:00",
       "Franja en la que se permite publicar (zona horaria de la plataforma)."),
    _s("publicaciones", "limite_diario", "Límite diario", "number", 24,
       "Tope de publicaciones por día en todos los canales.", minimum=1, maximum=500),
    _s("publicaciones", "retencion_publicados_dias", "Retener publicados en el panel", "number", 7,
       "Días que una publicación ya emitida sigue ocupando tarjeta en el Publicador. "
       "Pasado ese plazo libera el espacio para contenido nuevo; el registro se conserva "
       "en el Calendario Editorial. 0 = no retirar nunca.",
       minimum=0, maximum=365, unit="días", source="publicador._conservar"),
    _s("publicaciones", "refresco_horas", "Refrescar candidatos cada", "number", 12,
       "Cada cuántas horas el Publicador reemplaza sus tarjetas Pendiente por las "
       "mejores ofertas del momento. Lo generado, aprobado, programado o publicado "
       "nunca se toca. 0 desactiva el refresco automático.",
       minimum=0, maximum=168, unit="h", source="publicador._refrescar_si_toca"),
]

# ── 5. MARKETING ─────────────────────────────────────────────────────────────
_MARKETING = [
    _s("marketing", "cta_por_defecto", "CTA por defecto", "text", "👉 Link en bio 👇",
       "Llamado a la acción que se agrega al copy generado.", source="publicador._generar_contenido"),
    _s("marketing", "hashtags_globales", "Hashtags globales", "list",
       "#ofertasperu, #pricehunterpro, #descuentos, #peru",
       "Se agregan a toda publicación, además de los de tienda y categoría.",
       source="publicador._hashtags"),
    _s("marketing", "plantilla_por_defecto", "Plantilla por defecto", "select", "Top Oferta del Día",
       "Plantilla inicial de TikTok Factory.",
       options=("Flash Sale", "Mega Oferta", "Gaming", "Tecnología", "Hogar", "Top Oferta del Día"),
       source="tiktok.py _PLANTILLAS"),
    _s("marketing", "canal_por_defecto", "Canal por defecto", "select", "Telegram",
       "Canal preseleccionado al generar contenido.",
       options=("Telegram", "Facebook", "Instagram", "TikTok", "WhatsApp", "YouTube"),
       source="publicador.py CANALES"),
    _s("marketing", "color_marca", "Color de marca", "color", "#00E58F",
       "Color aplicado a las piezas gráficas generadas."),
    _s("marketing", "logo_oficial", "Logo oficial", "url", "/assets/logo_sidebar_transparente.png",
       "Logo estampado en las imágenes de TikTok Factory.", source="tiktok_image.py"),
]

# ── 6. ALERTAS ───────────────────────────────────────────────────────────────
_ALERTAS = [
    _s("alertas", "descuento_minimo", "Descuento mínimo", "number", 40,
       "Descuento mínimo para considerar una oferta alertable.",
       minimum=0, maximum=100, unit="%", source="deal_ranker SQL >= 0.40"),
    _s("alertas", "margen_minimo", "Margen mínimo", "number", 30,
       "Margen estimado mínimo.", minimum=0, maximum=1000, unit="%"),
    _s("alertas", "score_minimo", "Score mínimo", "number", 70,
       "PriceHunter Score mínimo para alertar.", minimum=0, maximum=100),
    _s("alertas", "precio_minimo", "Precio mínimo", "number", 50,
       "Por debajo de este precio no se alerta (evita la basura de centavos).",
       minimum=0, maximum=10000, unit="S/", source="pipeline de alertas current_price >= 50"),
    _s("alertas", "ahorro_minimo", "Ahorro mínimo", "number", 100,
       "Ahorro absoluto mínimo en soles.", minimum=0, maximum=10000, unit="S/",
       source="pipeline de alertas ahorro >= 100"),
    _s("alertas", "ratio_glitch_tarjeta", "Umbral de glitch con tarjeta", "number", 0.5,
       "Si el precio con tarjeta (CMR/Única) baja de esta fracción del precio público, "
       "se trata como glitch y se alerta aunque el precio público sea normal. "
       "Un descuento de tarjeta corriente es de 3-10%, así que 0,5 no da falsos positivos.",
       minimum=0.05, maximum=0.95, source="celery_app._notify_new_alerts"),
    _s("alertas", "frecuencia", "Frecuencia", "select", "Tiempo real",
       "Cada cuánto se evalúan y envían las alertas.",
       options=("Tiempo real", "Cada 15 minutos", "Cada hora", "Diaria")),
    _s("alertas", "prioridad", "Prioridad", "select", "Alta",
       "Prioridad con la que se encolan las alertas.", options=("Alta", "Media", "Baja")),
    _s("alertas", "envio_telegram", "Envío por Telegram", "bool", True,
       "Canal activo hoy.", source="telegram_notifier.py"),
    _s("alertas", "envio_email", "Envío por Email", "bool", False,
       "Requiere configurar SMTP en Integraciones.", preparado=True),
    _s("alertas", "envio_push", "Envío por Push", "bool", False,
       "Notificaciones push del navegador.", preparado=True),
]

# ── 7. SEGURIDAD ─────────────────────────────────────────────────────────────
_SEGURIDAD = [
    _s("seguridad", "jwt_expiration", "Expiración del JWT", "number", 1440,
       "Minutos de validez del token de sesión.",
       minimum=5, maximum=43200, unit="min", source="settings.jwt_expire_minutes"),
    _s("seguridad", "timeout_sesion", "Timeout de sesión", "number", 60,
       "Minutos de inactividad antes de cerrar sesión.", minimum=5, maximum=1440, unit="min"),
    _s("seguridad", "max_intentos_login", "Máximo de intentos de login", "number", 5,
       "Intentos fallidos antes de bloquear temporalmente.", minimum=1, maximum=20),
    _s("seguridad", "complejidad_password", "Complejidad de contraseña", "select", "Media",
       "Baja: 6+ caracteres · Media: 8+ con número · Alta: 12+ con símbolo y mayúscula.",
       options=("Baja", "Media", "Alta")),
    _s("seguridad", "doble_factor", "Doble factor (2FA)", "bool", False,
       "Segundo factor al iniciar sesión.", preparado=True),
    _s("seguridad", "auditoria", "Auditoría de cambios", "bool", True,
       "Registra usuario, fecha, valor anterior y nuevo de cada cambio de configuración."),
]

# ── 8. SISTEMA ───────────────────────────────────────────────────────────────
# Casi todo acá es LECTURA (lo sirve /settings/system-status). Solo se guardan
# los ajustes que sí son decisiones del administrador.
_SISTEMA = [
    # El AMBIENTE no se declara acá a propósito: lo fija `ENVIRONMENT` del .env y
    # es justo lo que decide QUÉ filas de configuración se leen. Un select en la
    # UI daría a entender que se puede cambiar en caliente, y no es así. Se
    # muestra como dato en las tarjetas de estado (`/settings/system-status`).
    _s("sistema", "modo_debug", "Modo debug", "bool", False,
       "Respuestas con traza detallada. No usar en producción."),
    _s("sistema", "cache_ttl", "TTL de caché", "number", 180,
       "Segundos que se cachea el catálogo de ofertas.",
       minimum=0, maximum=3600, unit="s", source="deal_service._CACHE_TTL_SECONDS"),
    _s("sistema", "limite_consulta_ofertas", "Límite de la consulta de ofertas", "number", 120000,
       "Tope de filas de la consulta principal. Al sumar una tienda grande hay que revisarlo.",
       minimum=1000, maximum=1000000, unit="filas", source="deal_service LIMIT"),
]

# ── 9. BASE DE DATOS ─────────────────────────────────────────────────────────
_BASE_DATOS = [
    _s("base_datos", "backup_automatico", "Backup automático", "bool", False,
       "Programar backups automáticos de la base.", preparado=True),
    _s("base_datos", "frecuencia_backup", "Frecuencia de backup", "select", "Diario",
       "Cada cuánto se genera el backup automático.",
       options=("Diario", "Semanal", "Mensual"), preparado=True),
    _s("base_datos", "retencion_historial", "Retención de historial de precios", "number", 90,
       "Días de `price_history` que se conservan.", minimum=7, maximum=3650, unit="días"),
]

# ── 10. INTEGRACIONES ────────────────────────────────────────────────────────
# Los 6 canales de publicación NO se declaran acá: ya los administra el módulo
# Canales (`/api/v1/channels`), con tokens cifrados. Esta pestaña los LEE de ahí
# y solo agrega las dos integraciones que ese módulo no cubre.
_INTEGRACIONES = [
    _s("integraciones", "openai_api_key", "OpenAI API Key", "text", "",
       "Clave para la generación de copy con IA avanzada.", preparado=True),
    _s("integraciones", "openai_modelo", "Modelo OpenAI", "text", "",
       "Modelo usado para generar contenido.", preparado=True),
    _s("integraciones", "smtp_host", "SMTP Host", "text", "", "Servidor de correo saliente.", preparado=True),
    _s("integraciones", "smtp_puerto", "SMTP Puerto", "number", 587, "Puerto SMTP.",
       minimum=1, maximum=65535, preparado=True),
    _s("integraciones", "smtp_usuario", "SMTP Usuario", "text", "", "Usuario del servidor SMTP.", preparado=True),
    _s("integraciones", "smtp_remitente", "SMTP Remitente", "text", "",
       "Dirección que aparece como remitente.", preparado=True),
]

CATALOGO: tuple[SettingDef, ...] = tuple(
    _GENERAL + _MOTOR_IA + _SCRAPERS + _PUBLICACIONES + _MARKETING
    + _ALERTAS + _SEGURIDAD + _SISTEMA + _BASE_DATOS + _INTEGRACIONES
)

_POR_CLAVE: dict[tuple[str, str], SettingDef] = {(d.category, d.key): d for d in CATALOGO}


def definicion(category: str, key: str) -> SettingDef | None:
    return _POR_CLAVE.get((category, key))


def por_categoria(category: str) -> list[SettingDef]:
    return [d for d in CATALOGO if d.category == category]


def categorias_validas() -> set[str]:
    return {c["id"] for c in CATEGORIAS}


# ── Conversión de valores ────────────────────────────────────────────────────
def to_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def from_text(texto: str | None, tipo: str) -> Any:
    """Texto de BD → valor tipado para la API."""
    if texto is None:
        return None
    if tipo == "bool":
        return str(texto).strip().lower() in ("true", "1", "yes", "si", "sí")
    if tipo == "number":
        try:
            f = float(texto)
            return int(f) if f.is_integer() else f
        except (TypeError, ValueError):
            return 0
    return texto


# ── Validación (regla 6: validar antes de guardar) ───────────────────────────
class ValidationError(ValueError):
    """Configuración inválida: el mensaje va tal cual al usuario."""


_HEX = set("0123456789abcdefABCDEF")


def validar_valor(d: SettingDef, valor: Any) -> Any:
    """Valida y normaliza un valor suelto. Devuelve el valor ya tipado."""
    if d.type == "bool":
        if isinstance(valor, bool):
            return valor
        return str(valor).strip().lower() in ("true", "1", "yes", "si", "sí")

    if d.type == "number":
        try:
            num = float(valor)
        except (TypeError, ValueError):
            raise ValidationError(f"«{d.label}» debe ser un número.")
        if d.minimum is not None and num < d.minimum:
            raise ValidationError(f"«{d.label}» no puede ser menor que {d.minimum}{d.unit and ' ' + d.unit}.")
        if d.maximum is not None and num > d.maximum:
            raise ValidationError(f"«{d.label}» no puede ser mayor que {d.maximum}{d.unit and ' ' + d.unit}.")
        return int(num) if num.is_integer() else num

    if d.type == "select":
        texto = str(valor)
        if d.options and texto not in d.options:
            raise ValidationError(f"«{d.label}»: «{texto}» no es una opción válida.")
        return texto

    if d.type == "color":
        texto = str(valor).strip()
        if not (texto.startswith("#") and len(texto) in (4, 7) and all(c in _HEX for c in texto[1:])):
            raise ValidationError(f"«{d.label}» debe ser un color hexadecimal, por ejemplo #00E58F.")
        return texto.upper()

    if d.type == "time_range":
        texto = str(valor).strip()
        partes = texto.split("-")
        if len(partes) != 2:
            raise ValidationError(f"«{d.label}» debe tener el formato HH:MM-HH:MM.")
        for p in partes:
            hm = p.strip().split(":")
            if len(hm) != 2 or not all(x.isdigit() for x in hm):
                raise ValidationError(f"«{d.label}» debe tener el formato HH:MM-HH:MM.")
            h, m = int(hm[0]), int(hm[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValidationError(f"«{d.label}»: «{p.strip()}» no es una hora válida.")
        return f"{partes[0].strip()}-{partes[1].strip()}"

    return str(valor)


_PESOS_IA = ("peso_descuento", "peso_margen", "peso_historico", "peso_tendencia", "peso_popularidad")


def validar_conjunto(valores: dict[tuple[str, str], Any]) -> None:
    """Validaciones que dependen de VARIOS campos a la vez.

    `valores` es el estado final completo (lo guardado + lo que se está por
    guardar), no solo el cambio, para poder cruzar campos.
    """
    # Los pesos del Motor IA reparten los 100 puntos del score: si no suman 100,
    # el score deja de ser comparable con el histórico ya calculado.
    pesos = [valores.get(("motor_ia", k)) for k in _PESOS_IA]
    if all(p is not None for p in pesos):
        total = sum(float(p) for p in pesos)
        # 88 = el reparto actual del scorer (30 histórico + 25 descuento + 20 margen
        # + 8 tendencia + 5 popularidad). Los 10 pts de "en stock" no son
        # configurables, así que el máximo alcanzable sigue siendo 98 y el score se
        # recorta a 100. Si la suma cambia, el score deja de ser comparable con el
        # histórico ya guardado.
        if abs(total - 88) > 0.01:
            raise ValidationError(
                f"Los pesos del Motor IA suman {total:g} y deben sumar 88. "
                f"Los 10 puntos restantes hasta 98 los aporta «en stock», que no es "
                f"configurable. Ajusta descuento, margen, histórico, tendencia o popularidad."
            )

    ganga = valores.get(("motor_ia", "score_minimo_ganga"))
    excelente = valores.get(("motor_ia", "score_minimo_excelente"))
    publicar = valores.get(("motor_ia", "score_minimo_publicar"))
    if ganga is not None and excelente is not None and float(ganga) <= float(excelente):
        raise ValidationError("El score de Ganga Extrema debe ser mayor que el de Excelente Oferta.")
    if excelente is not None and publicar is not None and float(excelente) < float(publicar):
        raise ValidationError("El score de Excelente Oferta no puede ser menor que el score mínimo para publicar.")

    por_hora = valores.get(("publicaciones", "publicaciones_por_hora"))
    intervalo = valores.get(("publicaciones", "intervalo_minimo"))
    if por_hora is not None and intervalo is not None:
        if float(por_hora) * float(intervalo) > 60:
            raise ValidationError(
                f"No caben {por_hora:g} publicaciones por hora con {intervalo:g} min de intervalo mínimo "
                f"(necesitarías {float(por_hora) * float(intervalo):g} min). Baja una de las dos."
            )

    diario = valores.get(("publicaciones", "limite_diario"))
    if por_hora is not None and diario is not None and float(diario) < float(por_hora):
        raise ValidationError("El límite diario no puede ser menor que el límite por hora.")

    auto = valores.get(("publicaciones", "publicar_automaticamente"))
    aprob = valores.get(("publicaciones", "requiere_aprobacion"))
    if auto and aprob:
        raise ValidationError(
            "«Publicar automáticamente» y «Requiere aprobación» se contradicen: desactiva una de las dos."
        )
