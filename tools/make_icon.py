"""Botアイコン（assets/focus-room-icon.png）を生成する。

使い方: python tools/make_icon.py   （Pillow が必要）
モチーフ: 夜の勉強部屋。開いた本と音符、外周はポモドーロの進み具合を表すリング。
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

S = 2048  # 作業解像度（最後に縮小してなめらかにする）
OUT = Path(__file__).resolve().parent.parent / "assets"

NAVY_TOP = (12, 18, 48)
NAVY_BOTTOM = (28, 40, 92)
AMBER = (255, 184, 82)
AMBER_HOT = (255, 214, 140)
PAGE = (246, 240, 226)
PAGE_SHADE = (214, 204, 184)
TRACK = (46, 62, 120)


def gradient() -> Image.Image:
    img = Image.new("RGB", (S, S))
    px = img.load()
    cx = cy = S / 2
    for y in range(S):
        for x in range(0, S):
            t = y / S
            r = math.hypot(x - cx, y - cy * 1.1) / (S * 0.75)
            k = min(1.0, max(0.0, t * 0.8 + (1 - r) * 0.25))
            px[x, y] = tuple(int(a + (b - a) * k) for a, b in zip(NAVY_TOP, NAVY_BOTTOM))
    return img


def glow(layer: Image.Image, radius: int, strength: float = 1.0) -> Image.Image:
    blurred = layer.filter(ImageFilter.GaussianBlur(radius))
    if strength != 1.0:
        blurred = Image.eval(blurred, lambda v: min(255, int(v * strength)))
    return blurred


def bezier(p0, p1, p2, n=40):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1])
            for t in (i / n for i in range(n + 1))]


def draw_book(d: ImageDraw.ImageDraw, cx: float, top: float, w: float, h: float) -> None:
    spine_top, spine_bottom = (cx, top + h * 0.10), (cx, top + h)
    for side in (-1, 1):
        outer_top = (cx + side * w, top)
        outer_bottom = (cx + side * w, top + h * 0.90)
        top_edge = bezier(spine_top, (cx + side * w * 0.45, top - h * 0.12), outer_top)
        bottom_edge = bezier(outer_bottom, (cx + side * w * 0.45, top + h * 0.80), spine_bottom)
        d.polygon(top_edge + bottom_edge, fill=PAGE)
        # 文字の行（淡い線）
        for i in range(5):
            f = 0.22 + i * 0.13
            y0 = top + h * f
            line = bezier((cx + side * w * 0.14, y0 + h * 0.06),
                          (cx + side * w * 0.5, y0 - h * 0.06), (cx + side * w * 0.86, y0))
            d.line(line, fill=PAGE_SHADE, width=int(S * 0.008))
    d.line([spine_top, spine_bottom], fill=PAGE_SHADE, width=int(S * 0.01))


def draw_note(d: ImageDraw.ImageDraw, x: float, y: float, size: float, color) -> None:
    """8分音符を2つ連桁でつないだ形。"""
    r = size * 0.22
    stem_w = size * 0.07
    gap = size * 0.62
    heads = [(x, y), (x + gap, y - size * 0.16)]
    for hx, hy in heads:
        d.ellipse([hx - r * 1.2, hy - r, hx + r * 1.2, hy + r], fill=color)
        d.rectangle([hx + r * 1.2 - stem_w, hy - size, hx + r * 1.2, hy], fill=color)
    (x1, y1), (x2, y2) = heads
    beam = size * 0.16
    d.polygon([(x1 + r * 1.2 - stem_w, y1 - size), (x2 + r * 1.2, y2 - size),
               (x2 + r * 1.2, y2 - size + beam), (x1 + r * 1.2 - stem_w, y1 - size + beam)],
              fill=color)


def main() -> None:
    random.seed(7)
    base = gradient()

    # 星
    stars = Image.new("L", (S, S), 0)
    sd = ImageDraw.Draw(stars)
    for _ in range(70):
        x, y = random.uniform(0, S), random.uniform(0, S * 0.62)
        if math.hypot(x - S / 2, y - S / 2) < S * 0.30:
            continue
        r = random.choice([3, 4, 5, 7])
        sd.ellipse([x - r, y - r, x + r, y + r], fill=random.randint(120, 230))
    base.paste((255, 244, 220), mask=ImageChops.lighter(stars, glow(stars, 6)))

    cx = cy = S / 2
    ring_r = S * 0.40
    ring_w = int(S * 0.045)
    box = [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r]

    # リング（土台）
    d = ImageDraw.Draw(base)
    d.ellipse(box, outline=TRACK, width=ring_w)

    # 進み具合の弧（暖色、発光）
    arc_layer = Image.new("L", (S, S), 0)
    ad = ImageDraw.Draw(arc_layer)
    start, end = -90, 200
    ad.arc(box, start, end, fill=255, width=ring_w)
    ex = cx + ring_r * math.cos(math.radians(end)) - ring_w / 2 + ring_w / 2
    ey = cy + ring_r * math.sin(math.radians(end))
    dot = ring_w * 0.95
    ad.ellipse([ex - dot, ey - dot, ex + dot, ey + dot], fill=255)
    base.paste(AMBER, mask=glow(arc_layer, 40, 0.9))
    base.paste(AMBER, mask=arc_layer)
    hot = Image.new("L", (S, S), 0)
    ImageDraw.Draw(hot).ellipse([ex - dot * 0.55, ey - dot * 0.55, ex + dot * 0.55, ey + dot * 0.55],
                                fill=255)
    base.paste(AMBER_HOT, mask=hot)

    # 本の下の暖かい光
    pool = Image.new("L", (S, S), 0)
    ImageDraw.Draw(pool).ellipse([cx - S * 0.26, cy + S * 0.02, cx + S * 0.26, cy + S * 0.30],
                                 fill=150)
    base.paste(AMBER, mask=glow(pool, 120))

    # 本
    book = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw_book(ImageDraw.Draw(book), cx, cy + S * 0.02, S * 0.22, S * 0.20)
    shadow = Image.new("L", (S, S), 0)
    shadow.paste(book.getchannel("A").point(lambda v: 110 if v else 0), (0, int(S * 0.02)))
    base.paste((5, 8, 24), mask=glow(shadow, 24))
    base.paste(book, mask=book)

    # 音符（本から立ちのぼる）
    note = Image.new("L", (S, S), 0)
    draw_note(ImageDraw.Draw(note), cx - S * 0.075, cy - S * 0.07, S * 0.20, 255)
    base.paste(AMBER, mask=glow(note, 30, 0.8))
    base.paste(AMBER_HOT, mask=note)

    OUT.mkdir(exist_ok=True)
    for size in (1024, 512):
        base.resize((size, size), Image.LANCZOS).save(OUT / f"focus-room-icon-{size}.png",
                                                      optimize=True)
    # Discordでの円形表示の見え方確認用
    preview = base.resize((512, 512), Image.LANCZOS)
    mask = Image.new("L", (512, 512), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, 511, 511], fill=255)
    circle = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    circle.paste(preview, mask=mask)
    circle.save(OUT / "focus-room-icon-preview-circle.png", optimize=True)
    print("saved to", OUT)


if __name__ == "__main__":
    main()
