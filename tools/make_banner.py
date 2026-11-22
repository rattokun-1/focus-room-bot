"""README用バナー（assets/banner.png）を生成する。

使い方: python tools/make_banner.py [フォントファイル]   （Pillow が必要）
フォントは Noto Sans JP（OFL）を想定。省略時は Windows の NotoSansJP-VF.ttf を探す。
先に tools/make_icon.py でアイコンを生成しておくこと。
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SCALE = 2
W, H = 1280 * SCALE, 420 * SCALE

NAVY_TOP = (12, 18, 48)
NAVY_BOTTOM = (30, 44, 98)
AMBER = (255, 184, 82)
TEXT = (246, 240, 226)
SUB = (190, 200, 235)
CHIP_BG = (38, 54, 112)

CHIPS = ["勉強時間の自動記録", "ランキング", "ポモドーロ", "YouTube Music BGM", "VC入室で自動開始"]


def font(path: str, size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, size)
    try:
        f.set_variation_by_name(weight)
    except (OSError, ValueError):
        pass  # 可変フォントでない場合
    return f


def find_font() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    for cand in (Path("C:/Windows/Fonts/NotoSansJP-VF.ttf"),
                 Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")):
        if cand.exists():
            return str(cand)
    raise SystemExit("Noto Sans JP のフォントファイルを引数で指定してください。")


def background() -> Image.Image:
    top = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / H
        top.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(NAVY_TOP, NAVY_BOTTOM)))
    img = top.resize((W, H))
    # 右下に暖かい光
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([int(W * 0.05), int(H * 0.15), int(W * 0.40), int(H * 1.25)], fill=90)
    img.paste(AMBER, mask=glow.filter(ImageFilter.GaussianBlur(160)))
    # 星
    random.seed(11)
    stars = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(stars)
    for _ in range(120):
        x, y = random.uniform(0, W), random.uniform(0, H)
        r = random.choice([2, 3, 3, 4, 6])
        sd.ellipse([x - r, y - r, x + r, y + r], fill=random.randint(90, 220))
    img.paste((255, 244, 220), mask=ImageChops.lighter(stars, stars.filter(ImageFilter.GaussianBlur(5))))
    return img


def main() -> None:
    fpath = find_font()
    img = background()
    d = ImageDraw.Draw(img)

    # アイコン（円形）
    icon_size = int(H * 0.72)
    icon = Image.open(ASSETS / "focus-room-icon-1024.png").convert("RGB").resize(
        (icon_size, icon_size), Image.LANCZOS)
    mask = Image.new("L", (icon_size, icon_size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, icon_size - 1, icon_size - 1], fill=255)
    ix, iy = int(W * 0.075), (H - icon_size) // 2
    halo = Image.new("L", (W, H), 0)
    ImageDraw.Draw(halo).ellipse([ix - 20, iy - 20, ix + icon_size + 20, iy + icon_size + 20], fill=140)
    img.paste(AMBER, mask=halo.filter(ImageFilter.GaussianBlur(50)))
    img.paste(icon, (ix, iy), mask)

    # 文字
    tx = ix + icon_size + int(W * 0.05)
    title = font(fpath, 120 * SCALE, "Bold")
    d.text((tx, int(H * 0.16)), "Focus Room", font=title, fill=TEXT)
    tagline = font(fpath, 34 * SCALE, "Medium")
    d.text((tx + 6, int(H * 0.50)), "勉強用VCの集中をサポートする Discord Bot", font=tagline, fill=SUB)

    # 機能のチップ
    chip_font = font(fpath, 22 * SCALE, "Bold")
    x, y = tx, int(H * 0.70)
    pad_x, pad_y, gap = 22 * SCALE, 10 * SCALE, 14 * SCALE
    for label in CHIPS:
        w = int(d.textlength(label, font=chip_font)) + pad_x * 2 + 26 * SCALE
        h = 22 * SCALE + pad_y * 2 + 6 * SCALE
        if x + w > W - int(W * 0.03):
            x, y = tx, y + h + gap
        d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=CHIP_BG)
        cy = y + h // 2
        r = 6 * SCALE
        d.ellipse([x + pad_x - r, cy - r, x + pad_x + r, cy + r], fill=AMBER)
        d.text((x + pad_x + 20 * SCALE, cy), label, font=chip_font, fill=TEXT, anchor="lm")
        x += w + gap

    out = img.resize((W // SCALE, H // SCALE), Image.LANCZOS)
    out.save(ASSETS / "banner.png", optimize=True)
    print("saved", ASSETS / "banner.png")


if __name__ == "__main__":
    main()
