# Diseño: separar el Redis de datos del broker de Celery

**Estado: PROPUESTA. No implementado.** Documento para revisión previa.

## El problema

Hoy una sola variable hace tres trabajos distintos ([celery_app.py:19](../backend/app/tasks/celery_app.py#L19)):

```python
app = Celery("pricehunter", broker=settings.redis_url, backend=settings.redis_url)
```

`REDIS_URL` es a la vez:

1. **Almacén de datos** de la app (usuarios, canales, plantillas, portafolio…).
2. **Broker** de Celery (la cola de tareas).
3. **Result backend** de Celery (resultados de cada tarea).

Mientras todo vivía en el mismo Redis local daba igual. Con Upstash deja de dar
igual: **un worker Celery en reposo no espera pasivamente**, hace `BRPOP` en
bucle contra el broker. A un comando por segundo son unos 86.400 al día, ~2,6 M
al mes: cinco veces los 500.000 del plan gratuito de Upstash. Al agotarse la
cuota, Upstash corta y la aplicación se queda sin usuarios, canales ni panel.

Es decir: apuntar Celery a Upstash **funcionaría técnicamente** —el worker local
consumiría las tareas que enviara Render— pero tumbaría la app en días.

## La separación propuesta

| Variable | Apunta a | Quién la usa |
|---|---|---|
| `REDIS_URL` | **Upstash** (persistente) | API web: datos de la aplicación |
| `CELERY_BROKER_URL` | **Redis local** (Docker) | Worker y beat locales |
| `CELERY_RESULT_BACKEND` | **Redis local**, o desactivado | Solo si se consultan resultados |

### Sobre `CELERY_RESULT_BACKEND`: ¿hace falta?

Sí, pero es el único punto que lo justifica: `/scrape/status` llama a
`AsyncResult(task_id)` para leer el estado de la tarea
([deals.py:80](../backend/app/api/v1/deals.py#L80)), y `monitoring.py` lee las
claves `celery-task-meta-*`. Sin result backend, esos endpoints dejarían de
informar del progreso.

**No debe apuntar a Upstash.** Cada tarea escribe su resultado y el frontend
lo consulta en bucle mientras hay un scrape en curso: es escritura y lectura
constante, justo lo que agota la cuota. Debe seguir en el Redis local, junto al
broker.

## Cambios mínimos

**1. `backend/app/core/config.py`** — dos campos nuevos que, si no se definen,
caen a `redis_url`. Así el entorno local sigue funcionando sin tocar nada:

```python
redis_url: str = "redis://redis:6379/0"
celery_broker_url: str = ""      # vacío -> usa redis_url
celery_result_backend: str = ""  # vacío -> usa el broker
```

**2. `backend/app/tasks/celery_app.py`** — resolver con respaldo:

```python
_broker = settings.celery_broker_url or settings.redis_url
_backend = settings.celery_result_backend or _broker
app = Celery("pricehunter", broker=_broker, backend=_backend)
```

**3. `.env` local** — sin cambios: al no definir las variables nuevas, todo
sigue apuntando al Redis del Docker, exactamente como hoy.

**4. Render** — define `REDIS_URL` (Upstash) y **no** define las de Celery.

Son dos archivos y unas seis líneas. No se toca ninguna lógica de negocio:
ni precios, ni scraping, ni historial, ni publicación.

## Consecuencia que hay que aceptar

Con broker local y API en Render, el botón "scrapear ahora" **desde producción
no dispararía el worker**: la petición encolaría una tarea en un broker que el
worker local no mira.

Ahora bien, **eso ya pasa hoy**: en Railway nunca hubo worker, así que esas
tareas se encolan y nadie las consume. No es una regresión, es el estado actual
descrito con precisión. El scraping real lo dispara el `celery-beat` local en
sus once franjas diarias.

Si en el futuro se quisiera disparar scrapes desde producción, las salidas son:
un broker accesible desde ambos lados (de pago), o un endpoint que el worker
local consulte por su cuenta.

## Orden de trabajo sugerido

1. Crear la base en Upstash (vacía).
2. Ejecutar `tools/migrar_redis_a_upstash.py --inventario` y revisar.
3. Migrar con `--migrar` y validar hashes.
4. **Solo entonces** aplicar esta separación en un commit propio.
5. Probar en local que el worker sigue consumiendo del Redis del Docker.
6. Desplegar en Render y verificar los 25 endpoints que dependen de Redis.
7. Al final de todo, y no antes, cambiar el proxy de Vercel.
