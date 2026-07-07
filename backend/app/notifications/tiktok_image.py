from __future__ import annotations

import io
import logging
import os
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

# ── Palette ───────────────────────────────────────────────────────────────────
BG        = (5,   8,   5)
BG_CARD   = (14,  18,  14)
BG_CARD2  = (10,  14,  10)
WHITE     = (255, 255, 255)
RED_LINE  = (220,  38,  38)
GREEN     = ( 0,  230,  80)
GREEN_DIM = ( 0,  170,  55)
GREEN_BG  = ( 8,   35,  12)
GREEN_BTN = ( 0,  180,  60)
GRAY      = (160, 160, 170)
GRAY_DIM  = (100, 100, 110)

STORE_COLORS = {
    "falabella": ( 34, 197,  94),
    "ripley":    (139,  92, 246),
    "plazavea":  (239,  68,  68),
    "oechsle":   (234, 179,   8),
    "promart":   (249, 115,  22),
    "tottus":    ( 59, 130, 246),
    "hiraoka":   ( 16, 185, 129),
    "estilos":   (236,  72, 153),
    "sodimac":   (255, 107,   0),
}
STORE_DISPLAY = {
    "falabella": "FALABELLA",
    "ripley":    "RIPLEY",
    "plazavea":  "PLAZAVEA",
    "oechsle":   "OECHSLE",
    "promart":   "PROMART",
    "tottus":    "TOTTUS",
    "hiraoka":   "HIRAOKA",
    "estilos":   "ESTILOS",
    "sodimac":   "SODIMAC",
}

LOGO_PATH = "/assets/logos/logo-completo.png"

# ── Fonts ─────────────────────────────────────────────────────────────────────
_BOLD = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
_REG = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for p in (_BOLD if bold else _REG):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default(size=size)


def _fetch_image(url: str) -> Image.Image | None:
    if not url:
        return None
    try:
        with httpx.Client(timeout=12, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"}) as c:
            r = c.get(url)
            if r.status_code == 200:
                return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception as exc:
        logger.warning("fetch_image error: %s", exc)
    return None


def _wrap(text: str, fnt: ImageFont.ImageFont, max_px: int,
          draw: ImageDraw.Draw, max_lines: int = 2) -> list[str]:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        test = f"{line} {word}".strip()
        if draw.textbbox((0, 0), test, font=fnt)[2] > max_px and line:
            lines.append(line)
            line = word
            if len(lines) == max_lines:
                break
        else:
            line = test
    if line and len(lines) < max_lines:
        lines.append(line)
    return lines


def _paste_logo(canvas: Image.Image, x: int, y: int, height: int) -> None:
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        w = int(logo.width * height / logo.height)
        logo = logo.resize((w, height), Image.LANCZOS)
        r, g, b, _ = logo.split()
        mask = Image.eval(r, lambda px: min(px * 2, 255))
        logo.putalpha(mask)
        canvas.paste(logo, (x, y), logo)
    except Exception as exc:
        logger.warning("Logo error: %s", exc)


def _lightning(d: ImageDraw.Draw, x: int, y: int, w: int, h: int, color: tuple) -> None:
    pts = [
        (x + w * 0.58, y),
        (x + w * 0.18, y + h * 0.48),
        (x + w * 0.50, y + h * 0.44),
        (x + w * 0.08, y + h),
        (x + w * 0.82, y + h * 0.52),
        (x + w * 0.48, y + h * 0.56),
    ]
    d.polygon(pts, fill=color)


def _rounded_rect_border(d: ImageDraw.Draw, box: tuple, radius: int,
                          fill: tuple, border: tuple, width: int = 2) -> None:
    d.rounded_rectangle(box, radius=radius, fill=fill)
    d.rounded_rectangle(box, radius=radius, outline=border, width=width)


def _clock_icon(d: ImageDraw.Draw, cx: int, cy: int, r: int, color: tuple) -> None:
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=3)
    d.line([(cx, cy - r + 5), (cx, cy), (cx + r // 2, cy)], fill=color, width=3)


def _telegram_icon(d: ImageDraw.Draw, cx: int, cy: int, r: int) -> None:
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GREEN_BTN)
    pts = [(cx - r//2, cy), (cx + r//2, cy - r//4), (cx, cy + r//2),
           (cx - r//8, cy + r//8), (cx + r//2, cy - r//4)]
    d.polygon([(cx - r*0.45, cy + r*0.05),
               (cx + r*0.55, cy - r*0.30),
               (cx + r*0.10, cy + r*0.50),
               (cx - r*0.05, cy + r*0.10)], fill=WHITE)


def _shield_icon(d: ImageDraw.Draw, cx: int, cy: int, r: int, color: tuple) -> None:
    pts = [(cx, cy - r), (cx + r, cy - r//2), (cx + r, cy + r//4),
           (cx, cy + r), (cx - r, cy + r//4), (cx - r, cy - r//2)]
    d.polygon(pts, outline=color, width=2)
    d.line([(cx - r//3, cy), (cx - r//8, cy + r//3), (cx + r//3, cy - r//4)],
           fill=color, width=3)


def _box_icon(d: ImageDraw.Draw, cx: int, cy: int, r: int, color: tuple) -> None:
    d.rectangle([cx - r, cy - r//2, cx + r, cy + r//2], outline=color, width=2)
    d.line([(cx - r, cy - r//2 + 7), (cx + r, cy - r//2 + 7)], fill=color, width=2)
    d.line([(cx, cy - r//2 + 7), (cx, cy + r//2)], fill=color, width=2)


def _cart_icon(d: ImageDraw.Draw, cx: int, cy: int, r: int, color: tuple) -> None:
    d.line([(cx - r, cy - r//2), (cx - r//2, cy + r//3), (cx + r, cy + r//3)],
           fill=color, width=3)
    d.ellipse([cx - r//4 - 4, cy + r//3, cx - r//4 + 4, cy + r//3 + 8], fill=color)
    d.ellipse([cx + r//2 - 4, cy + r//3, cx + r//2 + 4, cy + r//3 + 8], fill=color)


def _tag_icon(d: ImageDraw.Draw, cx: int, cy: int, r: int, color: tuple) -> None:
    pts = [(cx - r, cy), (cx - r//3, cy - r), (cx + r, cy - r//3),
           (cx + r, cy + r//3), (cx - r//3, cy + r)]
    d.polygon(pts, outline=color, width=2)
    d.ellipse([cx + r//4 - 3, cy - r//2 - 3, cx + r//4 + 3, cy - r//2 + 3], fill=color)


# ── Caption ───────────────────────────────────────────────────────────────────
def build_tiktok_caption(deal: dict[str, Any]) -> str:
    name     = deal.get("name", "Producto")
    current  = float(deal.get("currentPrice", 0))
    original = float(deal.get("originalPrice", 0))
    discount = float(deal.get("discountPct", 0))
    store    = STORE_DISPLAY.get(deal.get("store", ""), deal.get("store", "").upper())
    savings  = original - current
    category = deal.get("category", "")
    cat_tag  = "#" + category.replace(" ", "") if category else ""
    store_tag = "#" + store.replace(" ", "")
    return (
        f"Corre que se acaba! {discount:.0f}% de descuento en {store}\n\n"
        f"S/ {original:.2f} -> S/ {current:.2f}\n"
        f"Ahorras S/ {savings:.2f}!\n\n"
        f"{name}\n\n"
        f"Siguenos para mas gangas todos los dias\n\n"
        f"#OfertasPeru #GangasPeru #Descuentos {store_tag} {cat_tag} "
        f"#PriceHunterPro #Ahorra #Peru"
    )


# ── Main ──────────────────────────────────────────────────────────────────────
def generate_tiktok_image(deal: dict[str, Any]) -> bytes:
    W, H = 1080, 1920

    store    = deal.get("store", "").lower()
    name     = deal.get("name", "Producto")
    current  = float(deal.get("currentPrice", 0))
    original = float(deal.get("originalPrice", 0))
    discount = float(deal.get("discountPct", 0))
    savings  = original - current
    category = deal.get("category", "")
    img_url  = deal.get("imageUrl") or deal.get("image_url", "")

    s_color  = STORE_COLORS.get(store, GREEN)
    s_label  = STORE_DISPLAY.get(store, store.upper())

    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)

    # Subtle dot grid
    for gx in range(0, W, 50):
        for gy in range(0, H, 50):
            d.ellipse([gx - 1, gy - 1, gx + 1, gy + 1], fill=(14, 18, 14))

    # ── 1. HEADER (0-160) ────────────────────────────────────────────────────
    _paste_logo(canvas, x=24, y=24, height=72)

    # Tagline under logo
    f_tagline = _font(26)
    d.text((92, 106), "CAZAMOS LAS ", font=f_tagline, fill=WHITE)
    tw = d.textbbox((0, 0), "CAZAMOS LAS ", font=f_tagline)[2]
    d.text((92 + tw, 106), "MEJORES OFERTAS", font=f_tagline, fill=GREEN)

    # "OFERTA DETECTADA" badge top-right
    _rounded_rect_border(d, [W - 260, 18, W - 18, 148], radius=16,
                         fill=(5, 25, 8), border=GREEN, width=3)
    # Bell circle
    d.ellipse([W - 248, 28, W - 196, 80], fill=GREEN_DIM)
    # Bell shape (simple)
    d.ellipse([W - 238, 32, W - 206, 60], fill=WHITE)
    d.rectangle([W - 232, 52, W - 212, 68], fill=WHITE)
    d.ellipse([W - 228, 64, W - 216, 74], fill=WHITE)
    f_det = _font(34, bold=True)
    d.text((W - 188, 28), "OFERTA", font=f_det, fill=WHITE)
    d.text((W - 188, 68), "DETECTADA", font=f_det, fill=GREEN)

    # ── 2. OFERTA FLASH + product bg (160-760) ───────────────────────────────
    FLASH_Y1, FLASH_Y2 = 160, 760

    # Product image as background (right side)
    product = _fetch_image(img_url)
    if product:
        ph = FLASH_Y2 - FLASH_Y1
        pw = int(product.width * ph / product.height)
        product_rs = product.resize((pw, ph), Image.LANCZOS).convert("RGB")
        # Paste on right side
        px = W - pw if pw < W else 0
        canvas.paste(product_rs, (px, FLASH_Y1))
        # Dark overlay left-to-right gradient
        overlay = Image.new("RGBA", (W, ph), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for i in range(W):
            alpha = max(0, min(255, int(255 - (i / W) * 120)))
            od.line([(i, 0), (i, ph)], fill=(5, 8, 5, alpha))
        canvas.paste(Image.alpha_composite(
            canvas.crop([0, FLASH_Y1, W, FLASH_Y2]).convert("RGBA"), overlay
        ).convert("RGB"), (0, FLASH_Y1))

    # Lightning bolt
    _lightning(d, 28, 185, 88, 180, (255, 220, 0))

    # OFERTA
    f_oferta = _font(128, bold=True)
    d.text((126, 175), "OFERTA", font=f_oferta, fill=WHITE)

    # FLASH
    f_flash = _font(196, bold=True)
    d.text((22, 300), "FLASH", font=f_flash, fill=GREEN)

    # ── 3. POR TIEMPO LIMITADO (760-830) ────────────────────────────────────
    f_tiempo = _font(36, bold=True)
    tl_txt = "  POR TIEMPO LIMITADO"
    tw = d.textbbox((0, 0), tl_txt, font=f_tiempo)[2]
    _rounded_rect_border(d, [28, 768, 56 + tw, 826], radius=24,
                         fill=GREEN_BG, border=(0, 100, 30), width=1)
    _clock_icon(d, 58, 797, 16, GREEN)
    d.text((82, 778), tl_txt.strip(), font=f_tiempo, fill=(140, 255, 140))

    # ── 4. PRODUCT NAME + CATEGORY (840-1010) ────────────────────────────────
    f_name = _font(54, bold=True)
    name_lines = _wrap(name, f_name, W - 56, d, max_lines=2)
    ny = 845
    for line in name_lines:
        d.text((28, ny), line, font=f_name, fill=WHITE)
        ny += 66

    if category:
        f_cat = _font(36)
        d.text((28, ny + 4), category.upper(), font=f_cat, fill=GREEN)
    ny += 50

    # ── 5. PRICES (LEFT) + INFO CARDS (RIGHT) ────────────────────────────────
    COL_Y    = 1020
    LEFT_W   = 480
    RIGHT_X  = LEFT_W + 36
    RIGHT_W  = W - RIGHT_X - 24

    # LEFT: ANTES
    f_lbl  = _font(32)
    f_ante = _font(48)
    d.text((28, COL_Y), "ANTES", font=f_lbl, fill=GRAY)
    orig_txt = f"S/ {original:.2f}"
    ow = d.textbbox((0, 0), orig_txt, font=f_ante)[2]
    oh = d.textbbox((0, 0), orig_txt, font=f_ante)[3]
    d.text((28, COL_Y + 36), orig_txt, font=f_ante, fill=(130, 130, 140))
    d.line([28, COL_Y + 36 + oh // 2, 28 + ow, COL_Y + 36 + oh // 2],
           fill=RED_LINE, width=3)
    ay = COL_Y + 36 + oh + 18

    # AHORA pill
    f_ahora_l = _font(34, bold=True)
    f_ahora_p = _font(90, bold=True)
    d.rounded_rectangle([22, ay, 22 + LEFT_W - 4, ay + 148], radius=20, fill=GREEN_BTN)
    d.text((44, ay + 6), "AHORA", font=f_ahora_l, fill=WHITE)
    curr_txt = f"S/ {current:.2f}"
    d.text((44, ay + 44), curr_txt, font=f_ahora_p, fill=WHITE)
    ay += 162

    # AHORRAS pill
    f_sav = _font(36, bold=True)
    sav_txt = f"  AHORRAS  S/ {savings:.2f}"
    sw = d.textbbox((0, 0), sav_txt, font=f_sav)[2]
    _rounded_rect_border(d, [22, ay, 22 + LEFT_W - 4, ay + 62], radius=14,
                         fill=GREEN_BG, border=(0, 100, 30), width=1)
    _tag_icon(d, 46, ay + 31, 14, GREEN)
    d.text((70, ay + 14), sav_txt.strip(), font=f_sav, fill=GREEN)

    # RIGHT: info cards
    CARD_W  = RIGHT_W
    CARD_H  = 100
    CARD_X  = RIGHT_X
    cy      = COL_Y
    ICON_CX = CARD_X + 42
    f_card  = _font(30, bold=True)
    f_card_s = _font(24)
    GAP = 12

    # Store card
    _rounded_rect_border(d, [CARD_X, cy, CARD_X + CARD_W, cy + CARD_H],
                         radius=14, fill=BG_CARD, border=s_color, width=1)
    _cart_icon(d, ICON_CX, cy + CARD_H // 2, 22, s_color)
    d.text((CARD_X + 72, cy + 14), "DISPONIBLE EN", font=f_card_s, fill=GRAY)
    d.text((CARD_X + 72, cy + 44), s_label, font=f_card, fill=s_color)
    # Store color badge
    sw2 = d.textbbox((0, 0), s_label, font=f_card)[2]
    cy += CARD_H + GAP

    # Verified card
    _rounded_rect_border(d, [CARD_X, cy, CARD_X + CARD_W, cy + CARD_H],
                         radius=14, fill=BG_CARD, border=(30, 40, 30), width=1)
    _shield_icon(d, ICON_CX, cy + CARD_H // 2, 22, GREEN)
    d.text((CARD_X + 72, cy + 14), "OFERTA", font=f_card_s, fill=GRAY)
    d.text((CARD_X + 72, cy + 44), "VERIFICADA", font=f_card, fill=GREEN)
    # Green check circle right
    d.ellipse([CARD_X + CARD_W - 54, cy + 22, CARD_X + CARD_W - 10, cy + 78],
              fill=GREEN_BTN)
    d.line([(CARD_X + CARD_W - 44, cy + 50),
            (CARD_X + CARD_W - 34, cy + 62),
            (CARD_X + CARD_W - 18, cy + 36)], fill=WHITE, width=4)
    cy += CARD_H + GAP

    # Stock card
    _rounded_rect_border(d, [CARD_X, cy, CARD_X + CARD_W, cy + CARD_H],
                         radius=14, fill=BG_CARD, border=(30, 40, 30), width=1)
    _box_icon(d, ICON_CX, cy + CARD_H // 2, 22, GREEN)
    d.text((CARD_X + 72, cy + 14), "STOCK", font=f_card_s, fill=GRAY)
    d.text((CARD_X + 72, cy + 44), "DISPONIBLE", font=f_card, fill=GREEN)

    # ── 6. FOOTER: Telegram + TikTok (1430-1680) ────────────────────────────
    FOOT_Y = 1450
    d.rectangle([28, FOOT_Y - 10, W - 28, FOOT_Y - 8], fill=(25, 40, 25))

    HALF = (W - 56) // 2
    # Telegram card
    _rounded_rect_border(d, [28, FOOT_Y, 28 + HALF - 6, FOOT_Y + 210],
                         radius=16, fill=BG_CARD, border=GREEN, width=2)
    _telegram_icon(d, 90, FOOT_Y + 70, 36)
    f_join = _font(30, bold=True)
    f_join_s = _font(22)
    d.text((28 + HALF // 2, FOOT_Y + 120), "UNETE A NUESTRO", font=f_join_s,
           fill=GRAY, anchor="mm")
    d.text((28 + HALF // 2, FOOT_Y + 148), "CANAL DE TELEGRAM", font=f_join,
           fill=GREEN, anchor="mm")
    d.text((28 + HALF // 2, FOOT_Y + 180), "Y recibe mas ofertas como esta",
           font=f_join_s, fill=GRAY_DIM, anchor="mm")

    # TikTok card
    TT_X = 28 + HALF + 6
    _rounded_rect_border(d, [TT_X, FOOT_Y, TT_X + HALF, FOOT_Y + 210],
                         radius=16, fill=BG_CARD, border=(30, 40, 30), width=1)
    # QR placeholder
    qr_x, qr_y, qr_s = TT_X + 20, FOOT_Y + 20, 100
    d.rectangle([qr_x, qr_y, qr_x + qr_s, qr_y + qr_s], fill=WHITE)
    # QR inner pattern (simplified)
    for qi in range(3):
        for qj in range(3):
            if (qi + qj) % 2 == 0:
                d.rectangle([qr_x + 8 + qi * 28, qr_y + 8 + qj * 28,
                              qr_x + 28 + qi * 28, qr_y + 28 + qj * 28], fill=(0, 0, 0))
    # TikTok text
    d.text((TT_X + HALF // 2 + 10, FOOT_Y + 26), "ESCANEA Y", font=f_join_s,
           fill=GRAY, anchor="mm")
    d.text((TT_X + HALF // 2 + 10, FOOT_Y + 52), "SIGUENOS EN", font=f_join_s,
           fill=GRAY, anchor="mm")
    d.text((TT_X + HALF // 2 + 10, FOOT_Y + 84), "TIKTOK", font=f_join,
           fill=WHITE, anchor="mm")
    d.text((TT_X + HALF // 2 + 10, FOOT_Y + 124), "@pricehp", font=f_join,
           fill=GREEN, anchor="mm")

    # ── 7. BOTTOM FEATURES BAR (1690-1870) ────────────────────────────────────
    BAR_Y = 1700
    d.rectangle([0, BAR_Y - 2, W, BAR_Y], fill=(20, 50, 20))
    features = [
        ("CAZAMOS LAS", "MEJORES OFERTAS"),
        ("PRECIOS", "VERIFICADOS A DIARIO"),
        ("ALERTAS", "INSTANTANEAS"),
        ("HISTORIAL", "DE PRECIOS"),
    ]
    fw = W // 4
    f_feat_b = _font(22, bold=True)
    f_feat_s = _font(18)
    for i, (line1, line2) in enumerate(features):
        fx = i * fw + fw // 2
        # Simple icon circle
        d.ellipse([fx - 18, BAR_Y + 16, fx + 18, BAR_Y + 52], outline=GREEN, width=2)
        d.text((fx, BAR_Y + 62), line1, font=f_feat_b, fill=WHITE, anchor="mm")
        d.text((fx, BAR_Y + 86), line2, font=f_feat_s, fill=GREEN, anchor="mm")

    # ── 8. BOTTOM STRIPE ──────────────────────────────────────────────────────
    d.rectangle([0, H - 20, W, H], fill=s_color)

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=93, optimize=True)
    return out.getvalue()
