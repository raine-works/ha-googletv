"""Google TV by Raineworks' artwork: Google TV's icon, everywhere.

Draws every icon and banner from Google TV's icon (brand/google-tv.png): the
integration's brand icon (what Home Assistant and its Marketplace show), the TV
app's launcher icon, banner, in-app logo and status-bar icon, and the 512 px
project icon (android/play/icon-512.png, which raineworks.com and the README
show). One look for the integration and the TV app. Google TV is a trademark of
Google LLC; this project isn't affiliated with or endorsed by Google.
Run it from the repo root with Pillow: ``python brand/art.py``.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "android/app/src/main/res"
FONTS = RES / "font"
GOOGLE_TV = Image.open(ROOT / "brand/google-tv.png").convert("RGBA")
GOOGLE_TV = GOOGLE_TV.crop(GOOGLE_TV.getbbox())

# The TV app's dark background (its Theme.BACKGROUND)
BG = (10, 10, 10, 255)
FG = (250, 250, 250, 255)
MUTED = (161, 161, 161, 255)
NAME = "Google TV"
MAKER = "by Raineworks"


def google_tv_icon(size: int, width: float = 0.82) -> Image.Image:
    """Google TV's icon centred on a transparent square, ``width`` of its side."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    w = round(size * width)
    h = round(GOOGLE_TV.height * w / GOOGLE_TV.width)
    img.alpha_composite(
        GOOGLE_TV.resize((w, h), Image.LANCZOS), ((size - w) // 2, (size - h) // 2)
    )
    return img


def tile(size: int, width: float = 0.7) -> Image.Image:
    """Google TV's icon on the app's dark background (a launcher icon)."""
    img = Image.new("RGBA", (size, size), BG)
    img.alpha_composite(google_tv_icon(size, width))
    return img


def silhouette(size: int) -> Image.Image:
    """The icon's shape in white: Android tints a status-bar icon by its alpha."""
    shape = google_tv_icon(size, 0.92).getchannel("A")
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    img.putalpha(shape)
    return img


def lockup(
    size: tuple[int, int], logo_px: int, title_px: int, line_px: int
) -> Image.Image:
    """The icon, the name, and who made it under it, centred on the background."""
    img = Image.new("RGBA", size, BG)
    draw = ImageDraw.Draw(img)
    title = ImageFont.truetype(str(FONTS / "poppins_semibold.ttf"), title_px)
    small = ImageFont.truetype(str(FONTS / "poppins_regular.ttf"), line_px)
    tb = draw.textbbox((0, 0), NAME, font=title)
    lb = draw.textbbox((0, 0), MAKER, font=small)
    gap = round(logo_px * 0.28)
    text_w = max(tb[2] - tb[0], lb[2] - lb[0])
    x0 = (size[0] - (logo_px + gap + text_w)) // 2
    img.alpha_composite(google_tv_icon(logo_px, 1.0), (x0, (size[1] - logo_px) // 2))
    spacing = round(line_px * 0.55)
    block = (tb[3] - tb[1]) + spacing + (lb[3] - lb[1])
    top = (size[1] - block) // 2
    x = x0 + logo_px + gap
    draw.text((x - tb[0], top - tb[1]), NAME, font=title, fill=FG)
    draw.text(
        (x - lb[0] + 2, top + (tb[3] - tb[1]) + spacing - lb[1]),
        MAKER,
        font=small,
        fill=MUTED,
    )
    return img


def save(img: Image.Image, path: Path, opaque: bool = False) -> None:
    """Write ``img`` (RGB when ``opaque``), and say which file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    (img.convert("RGB") if opaque else img).save(path, optimize=True)
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    # Home Assistant's brand icon (its integrations page, the Marketplace)
    for px, name in ((256, "icon.png"), (512, "icon@2x.png")):
        save(google_tv_icon(px), ROOT / f"custom_components/googletv/brand/{name}")
    # The TV app: launcher icon, banner (320 x 180 dp), in-app logo, status-bar icon
    save(tile(192), RES / "drawable-xhdpi/icon.png", opaque=True)
    save(
        lockup((640, 360), 132, 52, 22), RES / "drawable-xhdpi/banner.png", opaque=True
    )
    save(google_tv_icon(192, 0.92), RES / "drawable-xhdpi/logo.png")
    save(silhouette(96), RES / "drawable-xhdpi/ic_stat_logo.png")
    # The project's 512 px icon, shown by raineworks.com and the README
    save(tile(512), ROOT / "android/play/icon-512.png", opaque=True)
