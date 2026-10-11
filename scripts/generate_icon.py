"""Build every Buzzcaf Studio logo asset from the brand sheet `logo.png`.

The sheet (repo root) holds the full logo on top and four app tiles below it;
the taskbar mock-up shows the third (light) and fourth (dark) tile in use.
This cuts them out and writes:

  assets/buzzcaf_studio.ico|png        dark tile - the exe / installer / shortcut icon
  assets/buzzcaf_studio_light.ico|png  light tile - window icon on a light taskbar
  assets/buzzcaf_studio_dark.ico|png   dark tile  - window icon on a dark taskbar
  frontend/public/favicon.ico, buzzcaf_studio.png     browser tab + apple-touch icon
  frontend/public/logo.png, logo-dark.png             full logo for light / dark themes
  frontend/public/logo-mark.png, logo-mark-dark.png   the B mark alone (collapsed sidebar)

Run `python scripts/generate_icon.py` after replacing logo.png. Needs Pillow + numpy.
"""

import os
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHEET = os.path.join(ROOT, "logo.png")
ASSETS = os.path.join(ROOT, "assets")
PUBLIC = os.path.join(ROOT, "frontend", "public")
ICO_SIZES = [256, 128, 64, 48, 32, 16]

# Where things sit on the 1536x1024 sheet (x0, y0, x1, y1), generous on purpose:
# the exact bounds are found from the pixels.
FULL_LOGO = (290, 70, 1290, 400)
MARK = (290, 70, 545, 400)
TILE_LIGHT = (785, 515, 1040, 775)
TILE_DARK = (1070, 515, 1330, 775)


def _sheet() -> Image.Image:
    if not os.path.isfile(SHEET):
        sys.exit(f"Brand sheet not found: {SHEET}")
    return Image.open(SHEET).convert("RGB")


def _to_alpha(img: Image.Image) -> np.ndarray:
    """Knock the sheet's white background out. Alpha grows with distance from
    white and saturates at full opacity for anything clearly coloured, so the
    orange and the ink stay solid on any theme; only the soft edge pixels are
    partly transparent (their colour is un-mixed from white). Float RGBA, 0..255."""
    a = np.asarray(img, dtype=np.float64)
    alpha = np.clip((255.0 - a.min(axis=2)) / 160.0, 0.0, 1.0)
    alpha = np.where(alpha < 0.12, 0.0, alpha)
    safe = np.maximum(alpha, 1e-4)[..., None]
    rgb = (a - 255.0 * (1.0 - safe)) / safe
    return np.dstack([np.clip(rgb, 0, 255), alpha * 255.0])


def _trim(rgba: np.ndarray, pad: int = 4) -> np.ndarray:
    ys, xs = np.where(rgba[..., 3] > 8)
    y0, y1, x0, x1 = max(ys.min() - pad, 0), ys.max() + pad + 1, max(xs.min() - pad, 0), xs.max() + pad + 1
    return rgba[y0:y1, x0:x1]


def _lighten_dark_ink(rgba: np.ndarray) -> np.ndarray:
    """For dark themes: the near-black ink becomes off-white, orange stays."""
    out = rgba.copy()
    rgb = out[..., :3]
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    dark = np.clip((200.0 - mx) / 40.0, 0, 1)             # how black the pixel is
    neutral = np.clip(1.0 - (mx - mn) / 100.0, 0, 1)      # bluish-black still counts
    w = np.clip(dark * neutral * 1.4, 0, 1)
    ink = np.array([246.0, 246.0, 248.0])
    out[..., :3] = rgb * (1 - w[..., None]) + ink * w[..., None]
    return out


def _png(rgba: np.ndarray, path: str, scale: float = 1.0) -> None:
    img = Image.fromarray(np.round(rgba).astype(np.uint8))
    if scale != 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    img.save(path, optimize=True)


def _crop(sheet: Image.Image, box) -> Image.Image:
    return sheet.crop(box)


def _tile(sheet: Image.Image, box, dark: bool) -> Image.Image:
    """The rounded app tile as a square RGBA image on a transparent background."""
    region = np.asarray(sheet.crop(box), dtype=np.int32)
    if dark:
        mask = region.max(axis=2) < 70                      # the tile is the only near-black area
    else:
        # cream tile on a white page: the tile is warmer (r > b); shadows are grey
        mask = (region[..., 0] - region[..., 2]) >= 4
    ys, xs = np.where(mask)
    # the tile is one big blob; ignore stray pixels by using robust percentiles
    y0, y1 = int(np.percentile(ys, 0.2)), int(np.percentile(ys, 99.8))
    x0, x1 = int(np.percentile(xs, 0.2)), int(np.percentile(xs, 99.8))
    side = min(x1 - x0, y1 - y0) + 1
    tile = sheet.crop((box[0] + x0, box[1] + y0, box[0] + x0 + side, box[1] + y0 + side))
    out = 1024
    tile = tile.resize((out, out), Image.LANCZOS).convert("RGBA")
    # rounded-square mask (super-sampled for a clean edge), eaten in a hair to drop the fringe
    ss = 4
    m = Image.new("L", (out * ss, out * ss), 0)
    inset = int(0.006 * out * ss)
    ImageDraw.Draw(m).rounded_rectangle([inset, inset, out * ss - inset, out * ss - inset],
                                        radius=int(0.225 * out * ss), fill=255)
    tile.putalpha(m.resize((out, out), Image.LANCZOS))
    return tile


def _save_icon(tile: Image.Image, name: str, folder: str) -> None:
    os.makedirs(folder, exist_ok=True)
    tile.resize((512, 512), Image.LANCZOS).save(os.path.join(folder, name + ".png"), optimize=True)
    tile.save(os.path.join(folder, name + ".ico"), format="ICO", sizes=[(s, s) for s in ICO_SIZES])


def generate_all() -> None:
    sheet = _sheet()

    light = _tile(sheet, TILE_LIGHT, dark=False)
    dark = _tile(sheet, TILE_DARK, dark=True)
    _save_icon(dark, "buzzcaf_studio", ASSETS)
    _save_icon(light, "buzzcaf_studio_light", ASSETS)
    _save_icon(dark, "buzzcaf_studio_dark", ASSETS)

    os.makedirs(PUBLIC, exist_ok=True)
    dark.resize((512, 512), Image.LANCZOS).save(os.path.join(PUBLIC, "buzzcaf_studio.png"), optimize=True)
    dark.save(os.path.join(PUBLIC, "favicon.ico"), format="ICO", sizes=[(s, s) for s in ICO_SIZES])

    for box, stem in ((FULL_LOGO, "logo"), (MARK, "logo-mark")):
        rgba = _trim(_to_alpha(_crop(sheet, box)))
        _png(rgba, os.path.join(PUBLIC, stem + ".png"))
        _png(_lighten_dark_ink(rgba), os.path.join(PUBLIC, stem + "-dark.png"))
    print("Logo assets written to assets/ and frontend/public/")


def create_buzzcaf_icon(output_path: str) -> None:
    """Entry point kept for scripts/build_windows_app.py: (re)builds every logo
    asset; `output_path` (assets/buzzcaf_studio.ico) is one of them."""
    generate_all()
    if not os.path.isfile(output_path):
        raise RuntimeError(f"Icon was not created: {output_path}")


if __name__ == "__main__":
    generate_all()
