"""Raineworks TV's artwork: the raineworks mark, Google TV's icon in its corner.

Draws every icon and banner (the TV app's launcher icon, banner, logo and
status-bar icon, Google Play's graphics) from the mark's geometry (raineworks'
blocks/brand) and brand/google-tv.png. The integration's brand icon, what Home
Assistant and its Marketplace show, is Google TV's icon alone: the integration
is for Google TV (Google TV is a trademark of Google LLC; this project isn't
affiliated with or endorsed by Google), and the TV app keeps the raineworks mark.
Run it from the repo root with Pillow: ``python brand/art.py``.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "android/app/src/main/res"
FONTS = RES / "font"
GOOGLE_TV = Image.open(ROOT / "brand/google-tv.png").convert("RGBA")
GOOGLE_TV = GOOGLE_TV.crop(GOOGLE_TV.getbbox())

BG = (10, 10, 10, 255)
FG = (250, 250, 250, 255)
MUTED = (161, 161, 161, 255)
NAME = "Raineworks TV"
TAGLINE = "Home Assistant on Google TV"
# Drawn this many times larger, then scaled down: smooth edges
SS = 4


def mark(size: int, stroke: float = 4.4, color=FG) -> Image.Image:
    """The mark alone, ``size`` across (its circle 92 of 96 units)."""
    s = size * SS / 96
    img = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w = max(1, round(stroke * s))

    def p(x: float, y: float) -> tuple[float, float]:
        return ((x + 48) * s, (y + 48) * s)

    def dot(x: float, y: float) -> None:
        cx, cy = p(x, y)
        draw.ellipse((cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2), fill=color)

    def ring(x: float, y: float, r: float) -> None:
        cx, cy = p(x, y)
        draw.ellipse(
            (
                cx - r * s - w / 2,
                cy - r * s - w / 2,
                cx + r * s + w / 2,
                cy + r * s + w / 2,
            ),
            outline=color,
            width=w,
        )

    ring(0, 0, 46)
    for a, b in (
        ((-22.98, -6.72), (-35.36, 5.66)),
        ((-2.83, -14.14), (-34.29, 17.32)),
        ((12.02, -16.26), (-30.05, 25.81)),
    ):
        draw.line((p(*a), p(*b)), fill=color, width=w)
        dot(*a)
        dot(*b)
    trace = [(-22.98, 31.47), (2.83, 5.66), (22.9, 5.66)]
    draw.line([p(*t) for t in trace], fill=color, width=w, joint="curve")
    dot(*trace[0])
    ring(26.6, 5.66, 3.7)
    return img.resize((size, size), Image.LANCZOS)


def logo(size: int, stroke: float = 4.4, badge: float = 0.46) -> Image.Image:
    """The mark with Google TV's icon over its top-right, a clear gap around it."""
    img = mark(size, stroke)
    bw = round(size * badge)
    gtv = GOOGLE_TV.resize(
        (bw, round(GOOGLE_TV.height * bw / GOOGLE_TV.width)), Image.LANCZOS
    )
    x, y = size - gtv.width, 0
    # The gap: the mark cleared a little past the badge's edge
    gap = max(2, round(size * 0.045))
    clear = Image.new("L", img.size, 255)
    ImageDraw.Draw(clear).rounded_rectangle(
        (x - gap, -gap, size + gap, gtv.height + gap),
        radius=round(gtv.height * 0.24) + gap,
        fill=0,
    )
    img.putalpha(
        Image.composite(img.getchannel("A"), Image.new("L", img.size, 0), clear)
    )
    img.alpha_composite(gtv, (x, y))
    return img


def tile(
    size: int, inset: float, radius: float = 0.0, stroke: float = 4.4
) -> Image.Image:
    """The logo on the dark background, rounded by ``radius`` (of the size)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=round(size * radius), fill=BG
    )
    inner = round(size * (1 - 2 * inset))
    art = logo(inner, stroke)
    img.alpha_composite(art, ((size - inner) // 2, (size - inner) // 2))
    return img


def lockup(
    size: tuple[int, int],
    logo_px: int,
    title_px: int,
    line_px: int,
    line: str = TAGLINE,
) -> Image.Image:
    """The logo, the name, and a line under it, centred on the background."""
    img = Image.new("RGBA", size, BG)
    draw = ImageDraw.Draw(img)
    title = ImageFont.truetype(str(FONTS / "poppins_semibold.ttf"), title_px)
    small = ImageFont.truetype(str(FONTS / "poppins_regular.ttf"), line_px)
    tb = draw.textbbox((0, 0), NAME, font=title)
    lb = draw.textbbox((0, 0), line, font=small)
    gap = round(logo_px * 0.28)
    text_w = max(tb[2] - tb[0], lb[2] - lb[0])
    x0 = (size[0] - (logo_px + gap + text_w)) // 2
    img.alpha_composite(logo(logo_px, 4.8), (x0, (size[1] - logo_px) // 2))
    spacing = round(line_px * 0.55)
    block = (tb[3] - tb[1]) + spacing + (lb[3] - lb[1])
    top = (size[1] - block) // 2
    x = x0 + logo_px + gap
    draw.text((x - tb[0], top - tb[1]), NAME, font=title, fill=FG)
    draw.text(
        (x - lb[0] + 2, top + (tb[3] - tb[1]) + spacing - lb[1]),
        line,
        font=small,
        fill=MUTED,
    )
    return img


def save(img: Image.Image, path: Path, opaque: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    (img.convert("RGB") if opaque else img).save(path, optimize=True)
    print(path.relative_to(ROOT))


def google_tv_icon(size: int, width: float = 0.82) -> Image.Image:
    """Google TV's icon centered on a transparent square, `width` of its side."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    w = round(size * width)
    h = round(GOOGLE_TV.height * w / GOOGLE_TV.width)
    img.alpha_composite(
        GOOGLE_TV.resize((w, h), Image.LANCZOS), ((size - w) // 2, (size - h) // 2)
    )
    return img


# Home Assistant's brand icon (its integrations page, the Marketplace): Google TV's icon
for px, name in ((256, "icon.png"), (512, "icon@2x.png")):
    save(google_tv_icon(px), ROOT / f"custom_components/googletv/brand/{name}")
# The TV app: launcher icon, banner (320 x 180 dp), in-app logo, status-bar icon
save(tile(192, 0.17, 0.0), RES / "drawable-xhdpi/icon.png", opaque=True)
save(lockup((640, 360), 132, 48, 20), RES / "drawable-xhdpi/banner.png", opaque=True)
save(logo(192), RES / "drawable-xhdpi/logo.png")
save(mark(96, 6.0, (255, 255, 255, 255)), RES / "drawable-xhdpi/ic_stat_logo.png")
# Google Play: the hi-res icon (Play rounds it), the TV banner, the feature graphic
save(tile(512, 0.17, 0.0), ROOT / "android/play/icon-512.png", opaque=True)
save(
    lockup((1280, 720), 264, 96, 38),
    ROOT / "android/play/tv-banner-1280x720.png",
    opaque=True,
)
save(
    lockup((1024, 500), 200, 76, 30),
    ROOT / "android/play/feature-graphic-1024x500.png",
    opaque=True,
)
