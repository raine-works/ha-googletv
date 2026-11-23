"""Raineworks TV's artwork: the raineworks mark in its peach-to-teal gradient.

Draws every icon and banner of the TV app (launcher icon, banner, logo,
status-bar icon) and the 512 px project icon (android/play/icon-512.png, which
raineworks.com shows as the project's logo) from the mark's geometry and
gradient (raineworks' blocks/brand): Raineworks' own, with nothing of Google's.
The integration's brand icon, what
Home Assistant and its Marketplace show, is Google TV's icon
(brand/google-tv.png): the integration is for Google TV (a trademark of Google
LLC; this project isn't affiliated with or endorsed by Google).
Run it from the repo root with Pillow: ``python brand/art.py``.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "android/app/src/main/res"
FONTS = RES / "font"
GOOGLE_TV = Image.open(ROOT / "brand/google-tv.png").convert(
    "RGBA"
)  # the integration's icon
GOOGLE_TV = GOOGLE_TV.crop(GOOGLE_TV.getbbox())

BG = (10, 10, 10, 255)
# raineworks' accent gradient, top left to bottom right across the band the
# rain lines fill (-17 to 17 in the mark's units): the circle beyond it is the
# two colours as they are
PEACH = (234, 154, 126)
TEAL = (41, 152, 173)
FG = (250, 250, 250, 255)
MUTED = (161, 161, 161, 255)
NAME = "Raineworks TV"
TAGLINE = "for Home Assistant"
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


def gradient_mark(size: int, stroke: float = 4.4) -> Image.Image:
    """The mark ``size`` across, stroked in raineworks' gradient."""
    shape = mark(size, stroke).getchannel("A")
    colors = []
    for y in range(size):
        for x in range(size):
            # Along the diagonal, in the mark's units (it's 96 across, centred)
            u = (x + 0.5) * 96 / size - 48
            v = (y + 0.5) * 96 / size - 48
            t = min(1.0, max(0.0, (u + v + 34) / 68))
            colors.append(
                tuple(round(a + (b - a) * t) for a, b in zip(PEACH, TEAL, strict=True))
            )
    img = Image.new("RGB", (size, size))
    img.putdata(colors)
    img = img.convert("RGBA")
    img.putalpha(shape)
    return img


def logo(size: int, stroke: float = 4.4) -> Image.Image:
    """The logo: the mark in its gradient."""
    return gradient_mark(size, stroke)


def glow(size: int) -> Image.Image:
    """A soft teal light, low in the middle, as Raineworks' integration icons have."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = []
    for y in range(size):
        for x in range(size):
            d = ((x / size - 0.5) ** 2 + (y / size - 0.66) ** 2) ** 0.5 / 0.55
            pixels.append((*TEAL, round(255 * 0.28 * max(0.0, 1 - d))))
    img.putdata(pixels)
    return img


def tile(
    size: int, inset: float, radius: float = 0.0, stroke: float = 4.4
) -> Image.Image:
    """The logo on the dark background and its glow, rounded by ``radius``."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shape = Image.new("L", (size, size), 0)
    ImageDraw.Draw(shape).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=round(size * radius), fill=255
    )
    back = Image.new("RGBA", (size, size), BG)
    back.alpha_composite(glow(size))
    img.paste(back, (0, 0), shape)
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
# The project's 512 px icon, shown by raineworks.com
save(tile(512, 0.17, 0.0), ROOT / "android/play/icon-512.png", opaque=True)
