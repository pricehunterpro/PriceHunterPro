"""Copy de Telegram y selección de ofertas: descuento real, escape y pie de invitación.

Son pruebas puras (sin base de datos ni red): el mensaje se arma con un dict.
"""
from app.notifications import telegram
from app.services.deal_ranker import seleccionar_top


def _deal(**kw):
    base = {
        "id": 1, "name": "Samsung Galaxy A15 128GB", "store": "falabella",
        "brand": "Samsung", "category": "Celulares",
        "currentPrice": 599.0, "originalPrice": 999.0, "discountPct": 40.0,
        "url": "https://www.falabella.com.pe/p/1", "imageUrl": "",
    }
    base.update(kw)
    return base


def _sin_invitacion(monkeypatch, enlace=""):
    monkeypatch.setattr(telegram, "enlace_canal", lambda canal=None: enlace)


# ── Mensaje ───────────────────────────────────────────────────────────────────

def test_el_antes_va_con_html_y_no_con_tildes_literales(monkeypatch):
    """`~~x~~` no es tachado en Telegram: se veía con las tildes puestas."""
    _sin_invitacion(monkeypatch)
    cap = telegram._build_caption(_deal())
    assert "~~" not in cap
    assert "<s>S/ 999.00</s>" in cap


def test_nombre_con_caracteres_especiales_no_rompe_el_mensaje(monkeypatch):
    """Un `<`, `&` o `_` en el nombre hacía que Telegram rechazara el envío."""
    _sin_invitacion(monkeypatch)
    cap = telegram._build_caption(_deal(name='Laptop <14" & Co_Gamer *Pro*'))
    assert "&lt;14&quot; &amp; Co_Gamer *Pro*" in cap
    assert "<14" not in cap


def test_oferta_verificada_muestra_precio_habitual_y_no_el_de_la_tienda(monkeypatch):
    _sin_invitacion(monkeypatch)
    cap = telegram._build_caption(_deal(verificada=True, histMedian=799.0))
    assert "Precio verificado" in cap
    assert "<s>S/ 799.00</s>" in cap          # el habitual, no el 999 inflado
    assert "999" not in cap
    assert "25%" in cap                        # 1 - 599/799
    assert "Ahorras <b>S/ 200</b>" in cap


def test_oferta_sin_verificar_no_presume_verificacion(monkeypatch):
    _sin_invitacion(monkeypatch)
    cap = telegram._build_caption(_deal(verificada=False))
    assert "verificado" not in cap.lower()
    assert "<s>S/ 999.00</s>" in cap
    assert "-40%" in cap


def test_pie_de_invitacion_solo_si_hay_enlace(monkeypatch):
    _sin_invitacion(monkeypatch, "")
    assert "Únete al canal" not in telegram._build_caption(_deal())
    _sin_invitacion(monkeypatch, "https://t.me/pricehunter")
    assert '<a href="https://t.me/pricehunter">Únete al canal</a>' in telegram._build_caption(_deal())


def test_enlace_se_deduce_del_usuario_del_canal(monkeypatch):
    monkeypatch.setattr(
        "app.services.settings_service.get_setting", lambda *a, **k: ""
    )
    assert telegram.enlace_canal("@ofertas_pe") == "https://t.me/ofertas_pe"
    assert telegram.enlace_canal("-1001234567890") == ""    # ID numérico: sin enlace público


def test_sin_url_no_se_arma_un_enlace_vacio(monkeypatch):
    _sin_invitacion(monkeypatch)
    assert 'href=""' not in telegram._build_caption(_deal(url=""))


def test_recortar_no_parte_palabras():
    largo = "Smart TV Samsung 55 Pulgadas Crystal UHD 4K UN55DU7000 Gris"
    # el corte en 38 caería dentro de "UHD": se retrocede al espacio anterior
    assert telegram.recortar(largo, 38) == "Smart TV Samsung 55 Pulgadas Crystal…"
    assert telegram.recortar("Corto", 40) == "Corto"


# ── Selección ─────────────────────────────────────────────────────────────────

def _cand(i, precio, orig, marca="Samsung", **kw):
    return _deal(id=i, name=f"{marca} Producto {i}", brand=marca, currentPrice=precio,
                 originalPrice=orig, discountPct=(orig - precio) / orig * 100, **kw)


def test_la_verificada_gana_a_una_de_mayor_descuento_declarado():
    """Descuento declarado altísimo pero sin respaldo vs. una real más modesta."""
    inflada = _cand(1, 80, 800)                                        # -90% declarado, sin historial
    real = _cand(2, 90, 150, verificada=True, descReal=30.0, histMedian=128.0)
    orden = seleccionar_top([inflada, real], total=2, cupos={"barato": 2})
    assert [d["id"] for d in orden] == [2, 1]


def test_lo_no_verificable_sigue_rellenando_vacantes():
    """Sin historial no se descarta: una liquidación recién empezada no es falsa."""
    solo = [_cand(i, 80 + i, 300) for i in range(1, 4)]
    assert len(seleccionar_top(solo, total=3, cupos={"barato": 3})) == 3


def test_verificadas_conservan_la_variedad_por_tramo():
    pool = [
        _cand(1, 50, 120, verificada=True, descReal=35.0, histMedian=77.0),
        _cand(2, 60, 130, verificada=True, descReal=30.0, histMedian=86.0),
        _cand(3, 1800, 3000, verificada=True, descReal=40.0, histMedian=3000.0),
        _cand(4, 700, 1300, verificada=True, descReal=25.0, histMedian=933.0),
    ]
    tramos = [d["_tramo"] for d in seleccionar_top(pool, total=4, cupos={"barato": 2, "medio": 1, "premium": 1})]
    assert sorted(tramos) == ["barato", "barato", "medio", "premium"]
