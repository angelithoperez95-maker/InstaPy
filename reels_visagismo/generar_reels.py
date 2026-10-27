#!/usr/bin/env python3
"""Genera la serie de reels animados de visagismo para barbería (1080x1920, 30 fps).

Uso:
    python3 generar_reels.py                       # renderiza los 6 videos en ./videos
    python3 generar_reels.py --solo 1 3            # solo los videos 1 y 3
    python3 generar_reels.py --handle @angelpz.cutz --zona "6ta Sección · Mendoza" --direccion "Olascoaga 1978"
    python3 generar_reels.py --preview             # exporta un PNG por escena para revisar
    python3 generar_reels.py --voz voz             # con la locución clonada (ver clonar_voz.py)

Los videos salen sin locución (pista de audio en silencio) para que encima se grabe
la voz siguiendo los guiones de GUIONES.md, en CapCut / Instagram / TikTok.
"""
import argparse
import math
import os
import subprocess
import wave
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H, FPS = 1080, 1920, 30
SS = 2  # supersampling para los trazos vectoriales

BG_TOP = (14, 14, 16)
BG_BOT = (28, 24, 18)
WHITE = (245, 242, 235)
MUTED = (150, 145, 135)
GOLD = (212, 162, 76)
RED = (229, 72, 77)
GREEN = (72, 196, 122)
POLE = [(200, 40, 45), (245, 242, 235), (35, 70, 160), (245, 242, 235)]

FONT_DIR = "/usr/share/fonts/opentype/inter/"
F_BLACK = FONT_DIR + "InterDisplay-Black.otf"
F_BOLD = FONT_DIR + "InterDisplay-Bold.otf"
F_SEMI = FONT_DIR + "Inter-SemiBold.otf"

OPTS = {"handle": "", "zona": "", "direccion": "", "voz": ""}
HERE = os.path.dirname(os.path.abspath(__file__))
MATERIAL = os.path.join(HERE, "material")


# ---------------------------------------------------------------- utilidades
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(p):
    p = clamp(p)
    return 1 - (1 - p) ** 3


def ease_back(p):
    p = clamp(p)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


def prog(t, t0, dur):
    return clamp((t - t0) / dur) if dur > 0 else float(t >= t0)


@lru_cache(maxsize=None)
def font(path, size):
    return ImageFont.truetype(path, size)


@lru_cache(maxsize=1)
def background():
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * k) for a, b in zip(BG_TOP, BG_BOT)))
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([W * 0.1, H * 0.3, W * 0.9, H * 0.75], fill=40)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    img = Image.composite(Image.new("RGB", (W, H), (60, 48, 30)), img, glow)
    return img.convert("RGBA")


# ---------------------------------------------------------------- texto
def _tokens(text):
    """'hola *mundo*?' -> [[(seg, resaltado), ...] por palabra] ; '\n' fuerza salto."""
    out, hl = [], False
    for line_i, line in enumerate(text.split("\n")):
        if line_i:
            out.append("\n")
        for word in line.split(" "):
            if not word:
                continue
            segs = []
            for j, part in enumerate(word.split("*")):
                if j:
                    hl = not hl
                if part:
                    segs.append((part, hl))
            if segs:
                out.append(segs)
    return out


@lru_cache(maxsize=None)
def text_img(text, size, max_w=940, color=WHITE, hl=GOLD, fpath=F_BLACK, spacing=1.08, upper=False):
    if upper:
        text = text.upper()
    f = font(fpath, size)
    space = f.getlength(" ")
    lines, cur, cur_w = [], [], 0
    for word in _tokens(text):
        if word == "\n":
            lines.append(cur)
            cur, cur_w = [], 0
            continue
        ww = sum(f.getlength(sg) for sg, _ in word)
        if cur and cur_w + space + ww > max_w:
            lines.append(cur)
            cur, cur_w = [], 0
        cur_w += (space if cur else 0) + ww
        cur.append((word, ww))
    lines.append(cur)
    lh = int(size * spacing)
    pad = 24
    img = Image.new("RGBA", (max_w + pad * 2, lh * len(lines) + pad * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(img), ImageDraw.Draw(shadow)
    for i, line in enumerate(lines):
        lw = sum(w for _, w in line) + space * max(0, len(line) - 1)
        x = pad + (max_w - lw) / 2
        y = pad + i * lh
        for word, ww in line:
            for sg, h in word:
                ds.text((x, y + 5), sg, font=f, fill=(0, 0, 0, 200))
                d.text((x, y), sg, font=f, fill=(hl if h else color) + (255,))
                x += f.getlength(sg)
            x += space
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    return Image.alpha_composite(shadow, img)


def with_alpha(img, a):
    if a >= 0.999:
        return img
    img = img.copy()
    img.putalpha(img.getchannel("A").point(lambda v: int(v * a)))
    return img


def put(frame, img, cx, cy, t=99, t0=0, anim="pop", dur=0.35):
    """Pega img centrada en (cx, cy) con animación de entrada."""
    p = prog(t, t0, dur)
    if p <= 0:
        return
    scale, a, dy = 1.0, ease_out(p), 0
    if anim == "pop":
        scale = 0.82 + 0.18 * ease_back(p)
    elif anim == "up":
        dy = int(60 * (1 - ease_out(p)))
    elif anim == "slam":
        scale = 1.6 - 0.6 * ease_out(p)
    if abs(scale - 1) > 0.005:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BILINEAR)
    img = with_alpha(img, a)
    frame.alpha_composite(img, (int(cx - img.width / 2), int(cy - img.height / 2 + dy)))


def pill(text, color, size=40, fg=(15, 15, 15)):
    f = font(F_BLACK, size)
    tw = f.getlength(text)
    img = Image.new("RGBA", (int(tw + size * 1.4), int(size * 1.9)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=img.height // 2, fill=color + (255,))
    d.text((img.width / 2, img.height / 2), text, font=f, fill=fg, anchor="mm")
    return img


# ---------------------------------------------------------------- rostro (vista frontal)
def _half_width(shape, y):
    """Medio ancho del contorno (unidades de S) para y en [-1 (coronilla), 1 (mentón)]."""
    a = abs(y)
    if shape == "oval":
        w = 0.70 * (1 - y * y) ** 0.5
        if y > 0:
            w *= 1 - 0.18 * y * y
    elif shape == "redondo":
        w = 0.86 * (1 - y * y) ** 0.47
    elif shape == "cuadrado":
        w = 0.80 * (1 - a ** 3) ** (1 / 3) if y < 0 else 0.80 * (1 - a ** 5) ** (1 / 5)
    elif shape == "alargado":
        w = 0.62 * (1 - a ** 3) ** (1 / 3) if y < 0 else 0.62 * (1 - a ** 4) ** (1 / 4)
    elif shape == "corazon":
        w = 0.80 * (1 - a ** 2.5) ** (1 / 2.5) if y < 0 else 0.80 * (1 - a ** 1.15) ** 0.8
    elif shape == "diamante":
        w = 0.66 * (1 - a ** 2.2) ** 0.55 if y < 0 else 0.66 * (1 - a ** 1.35) ** 0.8
        w += 0.12 * math.exp(-((y - 0.02) / 0.28) ** 2)  # pómulos marcados
    else:
        raise ValueError(shape)
    return max(0.0, w)


HEIGHT = {"oval": 1.0, "redondo": 0.86, "cuadrado": 0.95, "alargado": 1.13, "corazon": 1.0, "diamante": 1.04}


class Face:
    def __init__(self, shape, S):
        self.shape, self.S = shape, S * SS
        self.hy = HEIGHT[shape] * 1.25
        self.w = int(self.S * 3.6)
        self.h = int(self.S * (2 * self.hy + 1.6))
        self.cx = self.w / 2
        self.cy = self.S * (0.95 + self.hy)

    def X(self, xu):
        return self.cx + xu * self.S

    def Y(self, yu):
        return self.cy + yu * self.S * self.hy

    def edge(self, yu):
        return _half_width(self.shape, yu) * self.S

    def outline(self, n=140):
        right = []
        for i in range(n + 1):
            yu = -math.cos(math.pi * i / n)
            right.append((yu, self.cx + self.edge(yu), self.Y(yu)))
        left = [(yu, 2 * self.cx - x, y) for yu, x, y in reversed(right)]
        return right + left[1:]

    def side_pts(self, y0, y1, side, n=40):
        pts = []
        for i in range(n + 1):
            yu = y0 + (y1 - y0) * i / n
            pts.append((self.cx + side * self.edge(yu), self.Y(yu), yu))
        return pts


def _normal_offset(pts, thick):
    """pts: [(x, y)], thick: [px] -> puntos desplazados hacia afuera (sentido horario)."""
    out = []
    n = len(pts)
    for i, (x, y) in enumerate(pts):
        x0, y0 = pts[max(0, i - 1)]
        x1, y1 = pts[min(n - 1, i + 1)]
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy) or 1
        nx, ny = dy / L, -dx / L
        out.append((x + nx * thick[i], y + ny * thick[i]))
    return out


# Estilos de pelo: grosor (xu, yu) -> unidades de S, línea de nacimiento (xu) -> yu,
# hasta dónde baja el pelo por el costado (yu), y grosor del costado (fade).
def _bump(xu, c=0.0, wdt=0.55):
    return math.exp(-((xu - c) / wdt) ** 2)


def _top(yu, start=-0.45):
    return clamp((-yu + start) / (1 + start))


def _hairline_normal(xu):
    return -0.50 + 0.16 * xu * xu


def _hairline_entradas(xu):
    return -0.50 - 0.20 * math.exp(-((abs(xu) - 0.42) / 0.16) ** 2) + 0.16 * xu * xu


STYLES = {
    # bowl / flequillo recto con volumen a los costados (agranda el redondo)
    "bowl": dict(thick=lambda xu, yu: 0.17 + 0.03 * _top(yu), side_end=-0.12, side_t=0.17,
                 hairline=lambda xu: -0.30 + 0.06 * xu ** 8, side_fade=False),
    # tupé / quiff con costados bajos
    "quiff": dict(thick=lambda xu, yu: 0.04 + 0.46 * _top(yu, -0.35) ** 1.3 * _bump(xu, 0.12, 0.6),
                  side_end=0.02, side_t=0.035, hairline=_hairline_normal, side_fade=True),
    # pompa muy alta (alarga todavía más)
    "pompa_alta": dict(thick=lambda xu, yu: 0.04 + 0.72 * _top(yu, -0.3) ** 1.2 * _bump(xu, 0.05, 0.6),
                       side_end=0.02, side_t=0.02, hairline=_hairline_normal, side_fade=True),
    # ondulado medio con flequillo hacia adelante y costados con largo
    "ondulado": dict(thick=lambda xu, yu: 0.12 + 0.07 * _top(yu) + 0.02 * math.sin(yu * 30),
                     side_end=0.0, side_t=0.10,
                     hairline=lambda xu: -0.36 + 0.10 * xu * xu + 0.035 * math.sin(xu * 11), side_fade=True),
    # rizos tipo hongo: arriba bola, costados rapados al 0 con corte duro
    "rizos_hongo": dict(thick=lambda xu, yu: (0.30 + 0.05 * abs(math.sin(xu * 14 + yu * 9))) * (yu < -0.42),
                        side_end=-0.42, side_t=0.0, hairline=lambda xu: -0.48 + 0.06 * xu * xu,
                        side_fade=False),
    # rizos definidos con taper
    "rizos_taper": dict(thick=lambda xu, yu: 0.05 + (0.20 + 0.05 * abs(math.sin(xu * 14 + yu * 9))) * _top(yu, -0.3) ** 0.8,
                        side_end=0.02, side_t=0.04,
                        hairline=lambda xu: -0.44 + 0.10 * xu * xu + 0.03 * abs(math.sin(xu * 13)),
                        side_fade=True),
    # peinado hacia atrás que expone las entradas
    "atras": dict(thick=lambda xu, yu: 0.06 + 0.16 * _top(yu, -0.4), side_end=-0.1, side_t=0.04,
                  hairline=_hairline_entradas, side_fade=True),
    # crop texturizado con flequillo corto hacia adelante
    "crop": dict(thick=lambda xu, yu: 0.07 + 0.06 * _top(yu) + 0.015 * abs(math.sin(xu * 20)),
                 side_end=0.0, side_t=0.06,
                 hairline=lambda xu: -0.40 + 0.08 * xu * xu + 0.03 * ((int((xu + 1) * 9) % 2) * 2 - 1),
                 side_fade=True),
    # costados rapados alto, poco arriba (exagera pómulos en diamante)
    "rapado_alto": dict(thick=lambda xu, yu: 0.10 * (yu < -0.62) + 0.02, side_end=-0.62, side_t=0.0,
                        hairline=lambda xu: -0.58 + 0.04 * xu * xu, side_fade=False),
    # texturizado con algo de volumen al costado arriba y flequillo de lado (diamante)
    "lado": dict(thick=lambda xu, yu: 0.07 + 0.13 * _top(yu, -0.3) * _bump(xu, -0.25, 0.7),
                 side_end=0.0, side_t=0.06,
                 hairline=lambda xu: -0.36 + 0.14 * (xu + 1) ** 2 / 4 - 0.06 * xu, side_fade=True),
}

BEARDS = {
    "corta": lambda yu: 0.06,
    "menton": lambda yu: 0.05 + 0.20 * clamp((yu - 0.55) / 0.45) ** 1.5,
    "perfilada": lambda yu: 0.045 + 0.02 * clamp((yu - 0.6) / 0.4),
}


def _hair_polys(F, style, p):
    st = STYLES[style]
    ys = st["side_end"] if st["side_t"] == 0 else min(st["side_end"], -0.30)
    ys = max(ys, -0.98)
    # contorno superior desde la sien derecha, por arriba, hasta la sien izquierda
    pts, yus = [], []
    n = 80
    for i in range(n + 1):  # derecha: de ys hacia -1
        yu = ys + (-1 - ys) * (1 - math.cos(math.pi * i / n)) / 2
        pts.append((F.cx + F.edge(yu), F.Y(yu)))
        yus.append((1.0, yu))
    for i in range(1, n + 1):  # izquierda: de -1 hacia ys
        yu = -1 + (ys + 1) * (1 - math.cos(math.pi * i / n)) / 2
        pts.append((F.cx - F.edge(yu), F.Y(yu)))
        yus.append((-1.0, yu))
    # orden: sube por derecha y baja por izquierda => sentido antihorario en pantalla
    thick = []
    for (x, y), (side, yu) in zip(pts, yus):
        xu = (x - F.cx) / (F.edge(-0.3) or 1)
        thick.append(-st["thick"](xu, yu) * F.S * p)
    outer = _normal_offset(pts, thick)
    hl = []
    edge_ys = F.edge(ys)
    for i in range(41):
        xu = -1 + 2 * i / 40
        yl = st["hairline"](xu)
        k = abs(xu) ** 6
        yl = yl * (1 - k) + ys * k
        hl.append((F.cx + xu * edge_ys * 0.985, F.Y(yl)))
    polys = [outer + hl]
    sides = []
    if st["side_t"] > 0 and st["side_end"] > ys:
        for side in (1, -1):
            sp = F.side_pts(ys, st["side_end"], side, 30)
            base = [(x, y) for x, y, _ in sp]
            th = [side * -st["side_t"] * F.S * p * (1 if side < 0 else -1) * -1 for _ in sp]
            th = [st["side_t"] * F.S * p * (-1 if side > 0 else 1) for _ in sp]
            th = [-t for t in th] if side > 0 else th
            off = _normal_offset(base, [abs(t) * (1 if side > 0 else -1) for t in th])
            # garantizar que el desplazamiento quede hacia afuera
            if side > 0 and off[0][0] < base[0][0] or side < 0 and off[0][0] > base[0][0]:
                off = [(2 * bx - ox, 2 * by - oy) for (bx, by), (ox, oy) in zip(base, off)]
            inner = [(bx - side * st["side_t"] * F.S * 0.5 * p, by) for bx, by in base]
            sides.append((inner + list(reversed(off)), [y for _, _, y in sp]))
    return polys, sides, st["side_fade"]


@lru_cache(maxsize=256)
def face_layer(shape, S, style=None, hair_color=GOLD, outline_p=1.0, hair_p=1.0, beard=None,
               guides_p=0.0, features=True, mark_entradas=False, line=WHITE):
    F = Face(shape, S)
    img = Image.new("RGBA", (F.w, F.h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lw = int(5.5 * SS)
    ol = F.outline()
    xy = [(x, y) for _, x, y in ol]

    # orejas
    if outline_p >= 1:
        for side in (1, -1):
            ex = F.cx + side * F.edge(0.05)
            box = [ex - 0.10 * F.S, F.Y(-0.12), ex + 0.10 * F.S, F.Y(0.22)]
            d.chord(box, 270 if side > 0 else 90, 90 if side > 0 else 270, fill=BG_TOP + (255,),
                    outline=line + (255,), width=lw)
        # cuello
        for side in (1, -1):
            x0 = F.cx + side * F.edge(0.75) * 0.72
            d.line([(x0, F.Y(0.8)), (x0 + side * 0.06 * F.S, F.Y(1.45))], fill=line + (255,), width=lw)

    # relleno de cara (tapa el fondo para que el pelo del costado no se mezcle)
    if outline_p >= 1:
        d.polygon(xy, fill=(24, 22, 20, 255))

    # barba
    if beard and hair_p > 0:
        bf = BEARDS[beard]
        lower = [(x, y, yu) for yu, x, y in ol if yu > 0.15]
        base = [(x, y) for x, y, _ in lower]
        inner = []
        for x, y, yu in lower:
            dx, dy = x - F.cx, y - F.Y(0.25)
            L = math.hypot(dx, dy) or 1
            t = bf(yu) * F.S * hair_p
            inner.append((x - dx / L * t, y - dy / L * t))
        col = hair_color + (int(215 * min(1, hair_p * 1.5)),)
        d.polygon(base + list(reversed(inner)), fill=col)
        # bigote
        d.rounded_rectangle([F.cx - 0.20 * F.S, F.Y(0.30), F.cx + 0.20 * F.S, F.Y(0.36)], radius=10 * SS, fill=col)

    # contorno con trazo progresivo
    k = max(2, int(len(xy) * outline_p))
    d.line(xy[:k] + ([xy[0]] if outline_p >= 1 else []), fill=line + (255,), width=lw, joint="curve")

    # rasgos
    if features and outline_p >= 1:
        fw = int(4.5 * SS)
        mc = MUTED + (255,)
        for side in (1, -1):
            ex = F.cx + side * 0.27 * F.S
            d.line([(ex - 0.11 * F.S, F.Y(-0.17)), (ex + 0.11 * F.S, F.Y(-0.19 if side > 0 else -0.15))], fill=mc, width=fw)
            d.ellipse([ex - 0.05 * F.S, F.Y(-0.08), ex + 0.05 * F.S, F.Y(-0.02)], fill=mc)
        d.line([(F.cx + 0.02 * F.S, F.Y(-0.02)), (F.cx + 0.07 * F.S, F.Y(0.20)), (F.cx - 0.06 * F.S, F.Y(0.22))], fill=mc, width=fw)
        d.line([(F.cx - 0.15 * F.S, F.Y(0.42)), (F.cx + 0.15 * F.S, F.Y(0.42))], fill=mc, width=fw)

    # pelo
    if style and hair_p > 0:
        hp = ease_out(hair_p)
        polys, sides, fade = _hair_polys(F, style, hp)
        hair = Image.new("RGBA", img.size, (0, 0, 0, 0))
        hd = ImageDraw.Draw(hair)
        a = int(235 * min(1, hair_p * 1.5))
        for poly, yus in sides:
            if fade:
                # degradé: más transparente hacia abajo
                mask = Image.new("L", img.size, 0)
                ImageDraw.Draw(mask).polygon(poly, fill=255)
                grad = Image.new("L", img.size, 0)
                gd = ImageDraw.Draw(grad)
                y0, y1 = F.Y(yus[0]), F.Y(yus[-1])
                for yy in range(int(y0), int(y1) + 1, 2):
                    g = 1 - (yy - y0) / max(1, (y1 - y0))
                    gd.line([(0, yy), (img.width, yy)], fill=int(a * (0.15 + 0.85 * g)), width=2)
                gd.rectangle([0, 0, img.width, int(y0)], fill=a)
                layer = Image.new("RGBA", img.size, hair_color + (0,))
                layer.putalpha(Image.composite(grad, Image.new("L", img.size, 0), mask))
                hair = Image.alpha_composite(hair, layer)
                hd = ImageDraw.Draw(hair)
            else:
                hd.polygon(poly, fill=hair_color + (a,))
        for poly in polys:
            hd.polygon(poly, fill=hair_color + (a,))
        # mechones
        for poly in polys:
            hd.line(poly[: len(poly) - 41: 9], fill=(0, 0, 0, 60), width=int(3 * SS))
        img = Image.alpha_composite(img, hair)
        d = ImageDraw.Draw(img)

    if mark_entradas:
        for side in (1, -1):
            x = F.cx + side * 0.42 * F.edge(-0.5)
            r = 0.13 * F.S
            d.ellipse([x - r, F.Y(-0.62) - r, x + r, F.Y(-0.62) + r], outline=RED + (255,), width=lw)

    # guías de medición
    if guides_p > 0:
        gc = GOLD + (255,)
        gw = int(4 * SS)
        rows = [(-0.45, "FRENTE"), (0.02, "PÓMULOS"), (0.62, "MANDÍBULA")]
        f = font(F_BOLD, int(26 * SS))
        for i, (yu, label) in enumerate(rows):
            p = prog(guides_p, i * 0.22, 0.3)
            if p <= 0:
                continue
            half = F.edge(yu) * ease_out(p)
            y = F.Y(yu)
            _dashed(d, (F.cx - half, y), (F.cx + half, y), gc, gw)
            for s in (-1, 1):
                d.line([(F.cx + s * half, y - 14 * SS), (F.cx + s * half, y + 14 * SS)], fill=gc, width=gw)
            if p > 0.6:
                d.text((F.cx + F.edge(yu) + 0.10 * F.S, y), label, font=f, fill=gc, anchor="lm")
        p = prog(guides_p, 0.66, 0.34)
        if p > 0:
            x = F.cx - F.edge(0.02) - 0.38 * F.S
            y0, y1 = F.Y(-1), F.Y(-1) + (F.Y(1) - F.Y(-1)) * ease_out(p)
            _dashed(d, (x, y0), (x, y1), gc, gw)
            d.line([(x - 14 * SS, y0), (x + 14 * SS, y0)], fill=gc, width=gw)
            if p >= 1:
                d.line([(x - 14 * SS, y1), (x + 14 * SS, y1)], fill=gc, width=gw)
                d.text((x, y1 + 0.12 * F.S), "LARGO", font=f, fill=gc, anchor="mm")

    return img.reduce(SS)


def _dashed(d, a, b, fill, width, dash=16 * SS):
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    if L < 1:
        return
    n = int(L // dash)
    for i in range(0, n, 2):
        t0, t1 = i * dash / L, min(1, (i + 1) * dash / L)
        d.line([(a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)], fill=fill, width=width)


def put_face(frame, cx, cy, **kw):
    q = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in kw.items()}
    S = q.pop("S", 250)
    shape = q.pop("shape")
    img = face_layer(shape, S, **q)
    F = Face(shape, S)
    frame.alpha_composite(img, (int(cx - F.cx / SS), int(cy - F.cy / SS)))


# ---------------------------------------------------------------- cráneo (perfil)
def _catmull(pts, n=12):
    out = []
    P = [pts[0]] + pts + [pts[-1]]
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for j in range(n):
            t = j / n
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                                    + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in (0, 1)))
    out.append(pts[-1])
    return out


FRONT_PROFILE = [(-0.10, -0.98), (0.30, -0.90), (0.58, -0.55), (0.66, -0.28), (0.64, -0.16), (0.82, 0.03),
                 (0.67, 0.11), (0.71, 0.20), (0.65, 0.27), (0.69, 0.33), (0.64, 0.48), (0.45, 0.58),
                 (0.30, 0.64), (0.33, 1.05)]
BACK_ROUND = [(-0.30, 1.05), (-0.36, 0.55), (-0.52, 0.30), (-0.72, 0.00), (-0.72, -0.40), (-0.50, -0.82)]
BACK_FLAT = [(-0.30, 1.05), (-0.36, 0.55), (-0.46, 0.32), (-0.52, 0.05), (-0.55, -0.40), (-0.42, -0.84)]
BACK_LONG = [(-0.30, 1.05), (-0.36, 0.55), (-0.60, 0.30), (-0.90, 0.02), (-0.92, -0.42), (-0.62, -0.86)]


@lru_cache(maxsize=128)
def profile_layer(skull, S, outline_p=1.0, hair=None, hair_p=1.0, show_ideal=False, mark=None):
    S2 = S * SS
    w, h = int(S2 * 2.4), int(S2 * 2.6)
    cx, cy = w * 0.55, h * 0.42

    def P(pts):
        return [(cx + x * S2, cy + y * S2) for x, y in pts]

    back = {"redondo": BACK_ROUND, "plano": BACK_FLAT, "largo": BACK_LONG}[skull]
    curve = _catmull(back + FRONT_PROFILE, 10)
    xy = P(curve)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lw = int(5.5 * SS)
    if outline_p >= 1:
        d.polygon(xy, fill=(24, 22, 20, 255))
    # pelo de perfil
    if hair and hair_p > 0:
        hp = ease_out(hair_p)
        a = int(230 * min(1, hair_p * 1.5))
        top = _catmull(back[3:] + FRONT_PROFILE[:3], 10)
        if hair == "fade_alto":
            # pelo solo arriba, costado y nuca rapados: el occipital plano queda expuesto
            cap = [pt for pt in _catmull(back[4:] + FRONT_PROFILE[:3], 10)]
            inner = [(x, y) for x, y in cap]
            outer = [(x, y - 0.10 * hp) for x, y in cap]
            poly = P(outer) + list(reversed(P(inner)))
            d.polygon(poly, fill=GOLD + (a,))
        elif hair == "peso_atras":
            # el pelo rellena la curva que le falta al cráneo
            ideal = _catmull(BACK_ROUND[1:] + FRONT_PROFILE[:3], 10)
            ideal = [(x - 0.06 * hp, y - 0.07 * hp) for x, y in ideal]
            real = _catmull(back[1:] + FRONT_PROFILE[:3], 10)
            poly = P(ideal) + list(reversed(P(real)))
            # degradé en la nuca
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).polygon(poly, fill=GOLD + (a,))
            fade = Image.linear_gradient("L").resize(img.size).transpose(Image.FLIP_TOP_BOTTOM)
            m = fade.point(lambda v: 255 if v > 150 else int(60 + v * 195 / 150))
            layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", img.size, 0), m))
            img = Image.alpha_composite(img, layer)
            d = ImageDraw.Draw(img)
    k = max(2, int(len(xy) * outline_p))
    d.line(xy[:k], fill=WHITE + (255,), width=lw, joint="curve")
    if outline_p >= 1:
        ex, ey = cx - 0.05 * S2, cy + 0.04 * S2
        d.ellipse([ex - 0.11 * S2, ey - 0.17 * S2, ex + 0.11 * S2, ey + 0.17 * S2], outline=MUTED + (255,), width=int(4 * SS))
        d.line([(cx + 0.42 * S2, cy - 0.06 * S2), (cx + 0.52 * S2, cy - 0.06 * S2)], fill=MUTED + (255,), width=int(4 * SS))
    if show_ideal:
        ideal = P(_catmull(BACK_ROUND, 10))
        for i in range(0, len(ideal) - 1, 2):
            d.line([ideal[i], ideal[i + 1]], fill=GREEN + (255,), width=int(4 * SS))
    if mark:
        col = RED if mark == "plano" else GOLD
        x, y = cx + {"plano": -0.50, "largo": -0.78, "redondo": -0.62}[skull] * S2, cy - 0.20 * S2
        r = 0.28 * S2
        d.ellipse([x - r, y - r * 1.3, x + r, y + r * 1.3], outline=col + (255,), width=lw)
    return img.reduce(SS)


def put_profile(frame, cx, cy, skull, S=300, **kw):
    q = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in kw.items()}
    img = profile_layer(skull, S, **q)
    frame.alpha_composite(img, (int(cx - img.width / 2), int(cy - img.height / 2)))


# ---------------------------------------------------------------- iconos
@lru_cache(maxsize=None)
def stamp(kind, size=150):
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = RED if kind == "x" else GREEN
    d.ellipse([0, 0, s - 1, s - 1], fill=col + (255,))
    lw = int(s * 0.11)
    if kind == "x":
        m = s * 0.3
        d.line([(m, m), (s - m, s - m)], fill=WHITE + (255,), width=lw)
        d.line([(s - m, m), (m, s - m)], fill=WHITE + (255,), width=lw)
    else:
        d.line([(s * 0.27, s * 0.52), (s * 0.44, s * 0.69), (s * 0.74, s * 0.34)], fill=WHITE + (255,), width=lw, joint="curve")
    return img.reduce(SS)


# ---------------------------------------------------------------- marco común
def chrome(frame, T, total, idx, n_total):
    d = ImageDraw.Draw(frame)
    # franja de barbería animada
    sw = 36
    off = int(T * 60) % (sw * len(POLE))
    for i in range(-len(POLE), W // sw + len(POLE) * 2):
        x = i * sw - off
        d.polygon([(x, 0), (x + sw, 0), (x + sw - 14, 14), (x - 14, 14)], fill=POLE[i % len(POLE)])
    d.rectangle([0, 14, int(W * T / total), 20], fill=GOLD)
    chip = pill(f"VISAGISMO  ·  {idx}/{n_total}", GOLD, size=30)
    frame.alpha_composite(chip, ((W - chip.width) // 2, 70))
    if OPTS["handle"]:
        t = text_img(OPTS["handle"], 32, max_w=600, color=MUTED, fpath=F_SEMI)
        frame.alpha_composite(t, ((W - t.width) // 2, 112))


# ---------------------------------------------------------------- escenas reutilizables
TITLE_Y = 330
VIS_Y = 1010
SUB_Y = 1520


def sc_hook(lines, shape, style=None, color=RED, beard=None, stamp_kind="x"):
    def f(fr, t, dur):
        put(fr, text_img(lines, 92, upper=True), W / 2, TITLE_Y + 50, t, 0.0, "slam", 0.25)
        put_face(fr, W / 2, VIS_Y + 90, shape=shape, S=230, style=style, hair_color=color,
                 outline_p=ease_out(prog(t, 0.1, 0.7)), hair_p=prog(t, 0.6, 0.6), beard=beard)
        if stamp_kind and t > 1.3:
            put(fr, stamp(stamp_kind), W / 2 + 270, VIS_Y - 170, t, 1.3, "slam", 0.2)
    return f


def sc_face_text(title, sub, shape, style=None, color=GOLD, beard=None, stamp_kind=None, guides=False,
                 mark_entradas=False, S=230):
    def f(fr, t, dur):
        put(fr, text_img(title, 74), W / 2, TITLE_Y, t, 0.0, "pop")
        put_face(fr, W / 2, VIS_Y + 40, shape=shape, S=S, style=style, hair_color=color,
                 outline_p=ease_out(prog(t, 0.0, 0.6)), hair_p=prog(t, 0.5, 0.7) if style or beard else 0.0,
                 beard=beard, guides_p=prog(t, 0.6, 2.2) if guides else 0.0, mark_entradas=mark_entradas and t > 1.0)
        if stamp_kind and t > 1.2:
            put(fr, stamp(stamp_kind), W / 2 + 270, VIS_Y - 170, t, 1.2, "slam", 0.2)
        if sub:
            put(fr, text_img(sub, 50, color=WHITE, fpath=F_BOLD), W / 2, SUB_Y, t, 0.9, "up")
    return f


def sc_steps(title, steps, shape, style, beard=None, S=170):
    """Lista de pasos que aparece de a uno mientras el rostro se completa."""
    def f(fr, t, dur):
        put(fr, text_img(title, 70), W / 2, 280, t, 0.0, "pop")
        n = len(steps)
        step_t = (dur - 0.6) / n
        hp = prog(t, 0.4, step_t * n)
        put_face(fr, W / 2, 760, shape=shape, S=S, style=style, hair_color=GOLD, hair_p=hp, beard=beard)
        for i, s in enumerate(steps):
            t0 = 0.4 + i * step_t
            y = 1170 + i * 135
            if t < t0:
                continue
            num = pill(str(i + 1), GOLD, size=38)
            put(fr, num, 110, y, t, t0, "pop")
            img = text_img(s, 46, max_w=820, fpath=F_BOLD)
            p = ease_out(prog(t, t0, 0.35))
            fr.alpha_composite(with_alpha(img, p), (int(150 + 30 * (1 - p) - 24), int(y - img.height / 2)))
    return f


def sc_before_after(shape, bad, good, bad_beard=None, good_beard=None, title="ANTES  vs  DESPUÉS", sub=None):
    def f(fr, t, dur):
        put(fr, text_img(title, 78), W / 2, TITLE_Y, t, 0.0, "pop")
        put_face(fr, 285, VIS_Y, shape=shape, S=165, style=bad, hair_color=RED, beard=bad_beard)
        put(fr, stamp("x", 110), 285, VIS_Y + 390, t, 0.3, "slam", 0.2)
        wipe = ease_out(prog(t, 0.6, 0.8))
        if wipe > 0:
            put_face(fr, 795, VIS_Y, shape=shape, S=165, style=good, hair_color=GOLD, hair_p=wipe, beard=good_beard)
            put(fr, stamp("ok", 110), 795, VIS_Y + 390, t, 1.2, "slam", 0.2)
        d = ImageDraw.Draw(fr)
        d.line([(540, VIS_Y - 330), (540, VIS_Y + 330)], fill=MUTED, width=3)
        if sub:
            put(fr, text_img(sub, 50, fpath=F_BOLD), W / 2, SUB_Y + 60, t, 1.4, "up")
    return f


def sc_profile(title, sub, skull, hair=None, show_ideal=False, mark=None, stamp_kind=None, sub_t=1.0):
    def f(fr, t, dur):
        put(fr, text_img(title, 74), W / 2, TITLE_Y, t, 0.0, "pop")
        put_profile(fr, W / 2, VIS_Y + 30, skull, S=300, outline_p=ease_out(prog(t, 0.0, 0.8)),
                    hair=hair, hair_p=prog(t, 0.7, 0.9), show_ideal=show_ideal and t > 1.4, mark=mark if t > 1.1 else None)
        if stamp_kind and t > 1.5:
            put(fr, stamp(stamp_kind), W / 2 + 300, VIS_Y - 260, t, 1.5, "slam", 0.2)
        if sub:
            put(fr, text_img(sub, 50, fpath=F_BOLD), W / 2, SUB_Y + 40, t, sub_t, "up")
    return f


def sc_cta(main, offer, second, keyword):
    def f(fr, t, dur):
        put(fr, text_img(main, 84), W / 2, 520, t, 0.0, "slam", 0.25)
        put(fr, text_img(offer, 54, fpath=F_BOLD), W / 2, 850, t, 0.5, "up")
        if OPTS["zona"]:
            put(fr, pill(OPTS["zona"].upper(), WHITE, size=36), W / 2, 1010, t, 0.8, "pop")
        pulse = 1 + 0.05 * math.sin(max(0, t - 1.1) * 7)
        btn = pill(f"ESCRIBÍ  \"{keyword}\"  POR DM", GOLD, size=54)
        if t > 1.1:
            btn = btn.resize((int(btn.width * pulse), int(btn.height * pulse)), Image.BILINEAR)
        put(fr, btn, W / 2, 1170, t, 1.1, "pop")
        if OPTS["direccion"] or OPTS["handle"]:
            loc = "  ·  ".join(x for x in (OPTS["direccion"], OPTS["handle"]) if x)
            put(fr, text_img(loc, 46, fpath=F_BOLD, color=GOLD), W / 2, 1300, t, 1.4, "up")
        put(fr, text_img(second, 44, color=MUTED, fpath=F_SEMI, hl=WHITE), W / 2, 1440, t, 1.8, "up")
    return f


# ---------------------------------------------------------------- material real (videos / fotos del barbero)
CARD_W, CARD_H = 780, 1170


@lru_cache(maxsize=4)
def media_frames(name, w=CARD_W, h=CARD_H):
    path = os.path.join(MATERIAL, name)
    if name.lower().endswith((".jpg", ".jpeg", ".png")):
        img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        return [ImageOps.fit(img, (int(w * 1.15), int(h * 1.15)), Image.LANCZOS)]
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf",
                          f"fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    n = len(raw) // (w * h * 3)
    return [Image.frombuffer("RGB", (w, h), raw[i * w * h * 3:(i + 1) * w * h * 3]) for i in range(n)]


@lru_cache(maxsize=1)
def card_mask():
    m = Image.new("L", (CARD_W * 2, CARD_H * 2), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, CARD_W * 2 - 1, CARD_H * 2 - 1], radius=80, fill=255)
    return m.resize((CARD_W, CARD_H), Image.LANCZOS)


def media_at(name, t, dur):
    frames = media_frames(name)
    if len(frames) == 1:  # foto: zoom lento (Ken Burns)
        z = 1.15 - 0.12 * clamp(t / max(dur, 0.1))
        big = frames[0]
        cw, ch = int(CARD_W * z), int(CARD_H * z)
        x0, y0 = (big.width - cw) // 2, (big.height - ch) // 2
        return big.crop((x0, y0, x0 + cw, y0 + ch)).resize((CARD_W, CARD_H), Image.BILINEAR)
    i = int(t * FPS)
    n = len(frames)
    i %= 2 * n - 2  # ida y vuelta para que no corte
    return frames[i if i < n else 2 * n - 2 - i]


def sc_real(media, title, tag="TRABAJO REAL"):
    """Muestra cortes reales del barbero en una tarjeta. media: archivo o lista (montaje)."""
    items = [media] if isinstance(media, str) else list(media)
    if not all(os.path.exists(os.path.join(MATERIAL, m)) for m in items):
        return None

    def f(fr, t, dur):
        put(fr, text_img(title, 74), W / 2, 250, t, 0.0, "pop")
        seg = dur / len(items)
        k = min(len(items) - 1, int(t // seg))
        img = media_at(items[k], t - k * seg, seg).convert("RGBA")
        img.putalpha(card_mask())
        p = ease_out(prog(t, 0.0, 0.4))
        card = Image.new("RGBA", (CARD_W + 16, CARD_H + 16), (0, 0, 0, 0))
        ImageDraw.Draw(card).rounded_rectangle([0, 0, CARD_W + 15, CARD_H + 15], radius=48, fill=GOLD + (255,))
        card.alpha_composite(img, (8, 8))
        sc = 0.9 + 0.1 * p
        if sc < 0.999:
            card = card.resize((int(card.width * sc), int(card.height * sc)), Image.BILINEAR)
        cy = 990
        fr.alpha_composite(with_alpha(card, p), (int(W / 2 - card.width / 2), int(cy - card.height / 2)))
        label = tag + ("  ·  " + OPTS["handle"] if OPTS["handle"] else "")
        put(fr, pill(label, GOLD, size=34), W / 2, cy + CARD_H / 2 - 50, t, 0.5, "pop")
    return f


# ---------------------------------------------------------------- la serie
CTA_CLIENTE = "Antes de agarrar la máquina, *analizo tu rostro* y elegimos el corte juntos."
CTA_CURSO = "¿Sos barbero o querés serlo? *Enseño visagismo en mis cursos.*"


def serie():
    return [
        dict(slug="01_rostro_redondo_pelo_lacio", scenes=[
            (3.5, sc_hook("Cara *redonda*?\nDejá de pedir este corte", "redondo", "bowl")),
            (6.0, sc_face_text("Flequillo recto + volumen a los costados",
                               "Suma *ancho* donde ya sobra. Tu cara se ve *más redonda.*", "redondo", "bowl",
                               color=RED, stamp_kind="x")),
            (6.0, sc_face_text("Cómo saber si sos redondo",
                               "Largo y ancho casi *iguales* y mandíbula suave.", "redondo", guides=True)),
            (10.5, sc_steps("Lo que *sí* te favorece", [
                "*Volumen arriba* para estirar la cara",
                "Costados *bajos*: degradé medio",
                "Pelo lacio: *texturizar* para que se sostenga",
                "Barba corta que *marque ángulo*"], "redondo", "quiff", beard="perfilada")),
            (4.5, sc_before_after("redondo", "bowl", "quiff", good_beard="perfilada",
                                  sub="Mismo pibe. *Otro corte.*")),
            (4.5, sc_real("crop_textura.mov", "Así queda en *mi sillón*")),
            (6.0, sc_cta("¿Querés el corte que va con *tu cara*?", CTA_CLIENTE, CTA_CURSO, "TURNO")),
        ]),
        dict(slug="02_craneo_plano_degrade", scenes=[
            (3.5, lambda fr, t, d: (put(fr, text_img("Tu degradé alto te está *delatando*", 92, upper=True), W / 2, TITLE_Y + 50, t, 0, "slam", 0.25),
                                    put_profile(fr, W / 2, VIS_Y + 90, "plano", S=300, outline_p=ease_out(prog(t, 0.1, 0.8)),
                                                hair="fade_alto", hair_p=prog(t, 0.7, 0.6), mark="plano" if t > 1.4 else None))),
            (6.0, sc_profile("Mirate de *costado*", "Si atrás tu cabeza cae *recta*, tenés el occipital plano. Es re común.",
                             "plano", mark="plano")),
            (6.0, sc_profile("El rapado alto lo *expone*", "Sin pelo atrás, la parte plana queda *a la vista.*",
                             "plano", hair="fade_alto", mark="plano", stamp_kind="x")),
            (10.5, lambda fr, t, d: (
                put(fr, text_img("La solución: *dejar peso atrás*", 70), W / 2, 280, t, 0, "pop"),
                put_profile(fr, W / 2, 760, "plano", S=230, hair="peso_atras", hair_p=prog(t, 0.4, 2.0), show_ideal=t > 2.5),
                [put(fr, text_img(s, 46, max_w=900, fpath=F_BOLD), W / 2, 1220 + i * 130, t, 0.6 + i * 2.3, "up")
                 for i, s in enumerate(["Degradé *bajo* en la nuca", "Tijera en la *coronilla* para dar curva",
                                        "Pelo grueso: *desmechar*, no rapar", "El corte *dibuja* la cabeza que no tenés"])])),
            (4.5, sc_profile("Ahora la cabeza se ve *redonda*", "Esto es *visagismo*: cortar para tu cráneo, no para la foto.",
                             "plano", hair="peso_atras", show_ideal=True, stamp_kind="ok", sub_t=0.6)),
            (4.5, sc_real("nuca_diseno.jpg", "Así trabajo *la nuca*")),
            (6.0, sc_cta("¿Te pasa esto? *Vení y lo vemos.*", CTA_CLIENTE, CTA_CURSO, "CRÁNEO")),
        ]),
        dict(slug="03_cara_alargada_pelo_ondulado", scenes=[
            (3.5, sc_hook("Cara *larga*?\nNunca pidas esto", "alargado", "pompa_alta")),
            (6.0, sc_face_text("Más altura = cara *más larga*", "La pompa alta y los costados al 0 te *estiran* todavía más.",
                               "alargado", "pompa_alta", color=RED, stamp_kind="x")),
            (6.0, sc_face_text("Cómo saber si es alargada", "El largo le gana *claramente* al ancho. Frente alta.",
                               "alargado", guides=True)),
            (10.5, sc_steps("Lo que *sí* te favorece", [
                "Altura *moderada* arriba",
                "Costados con *algo de largo*",
                "Flequillo ondulado *hacia adelante*",
                "Aprovechá la *onda natural*"], "alargado", "ondulado", beard="corta")),
            (4.5, sc_before_after("alargado", "pompa_alta", "ondulado", good_beard="corta",
                                  sub="Se ve *más proporcionado* al toque.")),
            (4.5, sc_real("flequillo_adelante.mov", "Así queda en *mi sillón*")),
            (6.0, sc_cta("Tu cara tiene *su* corte.", CTA_CLIENTE, CTA_CURSO, "TURNO")),
        ]),
        dict(slug="04_cara_cuadrada_pelo_rizado", scenes=[
            (3.5, sc_hook("Cara cuadrada + *rulos*:\nel combo ganador", "cuadrado", "rizos_taper", color=GOLD,
                          beard="perfilada", stamp_kind="ok")),
            (6.0, sc_face_text("...si no te hacen *el hongo*", "Costados al 0 con línea dura y la bola arriba. *Error.*",
                               "cuadrado", "rizos_hongo", color=RED, stamp_kind="x")),
            (6.0, sc_face_text("Cómo saber si es cuadrada", "Frente y mandíbula *anchas* y casi rectas.",
                               "cuadrado", guides=True)),
            (10.5, sc_steps("Cómo se hace *bien*", [
                "*Taper* suave en sienes y nuca",
                "Rulos *definidos*, nunca aplastados",
                "Forma *redondeada* arriba",
                "Barba perfilada que *marque* la mandíbula"], "cuadrado", "rizos_taper", beard="perfilada")),
            (4.5, sc_before_after("cuadrado", "rizos_hongo", "rizos_taper", good_beard="perfilada",
                                  sub="Los rulos *se respetan*, no se esconden.")),
            (4.5, sc_real("rulos_barba.mov", "Rulos *de verdad*")),
            (6.0, sc_cta("¿Tenés *rulos*? Te los dejo *como tienen que estar.*", CTA_CLIENTE, CTA_CURSO, "RULOS")),
        ]),
        dict(slug="05_entradas_rostro_corazon_pelo_fino", scenes=[
            (3.5, sc_hook("¿*Entradas*?\nEste corte las disimula", "corazon", "crop", color=GOLD, stamp_kind="ok")),
            (6.0, sc_face_text("Peinarte para atrás las *expone*", "Frente ancha + entradas a la vista = frente *gigante.*",
                               "corazon", "atras", color=RED, stamp_kind="x", mark_entradas=True)),
            (6.0, sc_face_text("Rostro corazón", "Frente *ancha*, mentón *finito*. Pasa mucho con entradas.",
                               "corazon", guides=True)),
            (10.5, sc_steps("Lo que *sí* funciona", [
                "*Crop texturizado* hacia adelante",
                "Flequillo corto *irregular*",
                "Pelo fino: textura con *tijera*",
                "Barba que le dé *peso al mentón*"], "corazon", "crop", beard="menton")),
            (4.5, sc_before_after("corazon", "atras", "crop", good_beard="menton",
                                  sub="Las entradas *no se ven*. Y no es magia.")),
            (4.5, sc_real("crop_flequillo.mov", "Así queda en *mi sillón*")),
            (6.0, sc_cta("Las entradas *se trabajan*, no se esconden con gorra.", CTA_CLIENTE, CTA_CURSO, "TURNO")),
        ]),
        dict(slug="06_3_cosas_que_mira_un_barbero_curso", scenes=[
            (3.5, lambda fr, t, d: (put(fr, text_img("3 cosas que mira un barbero *que sabe*", 92, upper=True), W / 2, 420, t, 0, "slam", 0.25),
                                    put(fr, text_img("(y casi nadie te enseña)", 54, color=MUTED, fpath=F_BOLD), W / 2, 820, t, 0.8, "up"),
                                    put_face(fr, W / 2, 1270, shape="diamante", S=180, outline_p=ease_out(prog(t, 0.3, 0.8)), guides_p=prog(t, 1.0, 2.0)))),
            (6.5, sc_face_text("1. La forma del *rostro*", "Diamante: pómulos anchos. Rapar los costados *los exagera.*",
                               "diamante", "rapado_alto", color=RED, stamp_kind="x")),
            (6.5, sc_profile("2. La forma del *cráneo*", "Cabeza larga atrás: el degradé se sube *más* para equilibrar.",
                             "largo", mark="largo")),
            (6.0, sc_face_text("3. El *tipo de pelo*", "Lacio, ondulado, rizado, fino o grueso: *cada uno se corta distinto.*",
                               "diamante", "lado", color=GOLD, stamp_kind="ok")),
            (5.0, lambda fr, t, d: (put(fr, text_img("Rostro + cráneo + pelo =\n*TU* corte", 88), W / 2, 600, t, 0, "pop"),
                                    put(fr, text_img("Eso es *visagismo*. Y se aprende.", 56, fpath=F_BOLD), W / 2, 1050, t, 0.8, "up"))),
            (6.0, sc_real(["crop_textura.mov", "rulos_barba.mov", "flequillo_adelante.mov", "nuca_diseno.jpg", "crop_taper.mov"],
                         "Cortes *míos*", tag="ESTO VAS A APRENDER")),
            (7.0, sc_cta("¿Querés cortar *así*?", "Doy *cursos de barbería* con visagismo desde cero. Grupos chicos, práctica real.",
                         "¿Solo querés un buen corte? *Reservá tu turno.*", "CURSO")),
        ]),
    ]


# ---------------------------------------------------------------- render
def _read_wav16k(path):
    with wave.open(path) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2, path
        return w.readframes(w.getnframes())


def voice_track(video, path):
    """Arma la pista de voz y devuelve las duraciones de escena estiradas para que entre cada frase."""
    scenes, durs, clips = video["scenes"], [], []
    for i, (dur, fn) in enumerate(scenes, 1):
        if fn is None:
            durs.append(0)
            clips.append(b"")
            continue
        wp = os.path.join(OPTS["voz"], video["slug"], f"esc{i}.wav") if OPTS["voz"] else ""
        pcm = _read_wav16k(wp) if wp and os.path.exists(wp) else b""
        clips.append(pcm)
        # con voz, la escena dura lo que la frase (más un respiro); sin voz, lo que marca la serie
        need = len(pcm) / 32000 + 0.45
        durs.append(round(max(2.5, need) * FPS) / FPS if pcm else dur)
    if not any(clips):
        return durs, None
    out = bytearray()
    for d, pcm in zip(durs, clips):
        n = int(round(d * 16000)) * 2
        lead = 3200  # 0,1 s de aire antes de cada frase
        seg = (bytes(lead) + pcm)[:n]
        out += seg + bytes(n - len(seg))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(bytes(out))
    return durs, path


def render(video, idx, n_total, outdir, preview=False):
    scenes = video["scenes"]
    path = os.path.join(outdir, video["slug"] + ".mp4")
    durs, audio = voice_track(video, os.path.join(outdir, video["slug"] + "_voz.wav"))
    scenes = [(d, fn) for d, (_, fn) in zip(durs, scenes) if fn is not None]
    total = sum(d for d, _ in scenes)
    if preview:
        T = 0
        for i, (dur, fn) in enumerate(scenes):
            fr = background().copy()
            chrome(fr, T + dur * 0.9, total, idx, n_total)
            fn(fr, dur * 0.9, dur)
            fr.convert("RGB").save(os.path.join(outdir, f"{video['slug']}_esc{i + 1}.png"))
            T += dur
        return
    audio_in = ["-i", audio] if audio else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", *audio_in,
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", "-shortest", path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    T0 = 0.0
    for dur, fn in scenes:
        nf = int(round(dur * FPS))
        for i in range(nf):
            t = i / FPS
            fr = background().copy()
            chrome(fr, T0 + t, total, idx, n_total)
            fn(fr, t, dur)
            # fundido corto entre escenas
            if i < 4 and T0 > 0:
                fr = Image.blend(background(), fr, (i + 1) / 5)
            proc.stdin.write(fr.convert("RGB").tobytes())
        T0 += dur
    proc.stdin.close()
    proc.wait()
    if audio:
        os.remove(audio)
    print(f"OK {path} ({total:.1f}s{', con voz' if audio else ''})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", type=int, nargs="*")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "videos"))
    ap.add_argument("--handle", default="@angelpz.cutz")
    ap.add_argument("--zona", default="6ta Sección · Mendoza")
    ap.add_argument("--direccion", default="Olascoaga 1978")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--voz", default="", help="carpeta generada por clonar_voz.py (voz/<video>/escN.wav)")
    a = ap.parse_args()
    OPTS["handle"], OPTS["zona"], OPTS["direccion"], OPTS["voz"] = a.handle, a.zona, a.direccion, a.voz
    os.makedirs(a.out, exist_ok=True)
    vids = serie()
    for i, v in enumerate(vids, 1):
        if a.solo and i not in a.solo:
            continue
        render(v, i, len(vids), a.out, a.preview)


if __name__ == "__main__":
    main()
