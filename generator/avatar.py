"""Avatar image -> grid of (character, colour) cells. Knows nothing about SVG."""
import io

import requests
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from generator import config

Cell = tuple[str, str]


def fetch_avatar(username: str, size: int = config.AVATAR_FETCH_SIZE) -> Image.Image:
    url = config.AVATAR_URL.format(user=username, size=size)
    response = requests.get(url, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Avatar fetch failed for {username}: HTTP {response.status_code}")
    return Image.open(io.BytesIO(response.content)).convert("RGB")


def build_grid(image: Image.Image, cols: int = config.AVATAR_COLS) -> list[list[Cell]]:
    if cols <= 0:
        raise ValueError("cols must be positive")

    rgb = image.convert("RGB")
    width, height = rgb.size
    rows = max(1, round(cols * (height / width) * config.CHAR_ASPECT))

    # Luminance pass: autocontrast then sharpen, so a flat mid-tone background
    # does not swamp the portrait with a single ramp character.
    lum = ImageOps.autocontrast(rgb.convert("L"), cutoff=config.AUTOCONTRAST_CUTOFF)
    lum = ImageEnhance.Contrast(lum).enhance(config.CONTRAST_BOOST)
    lum = lum.filter(ImageFilter.SHARPEN)

    lum_small = lum.resize((cols, rows), Image.LANCZOS)
    rgb_small = rgb.resize((cols, rows), Image.LANCZOS)

    ramp = config.ASCII_RAMP
    last = len(ramp) - 1
    luminances = list(lum_small.getdata())
    colours = list(rgb_small.getdata())

    grid: list[list[Cell]] = []
    for row in range(rows):
        cells: list[Cell] = []
        for col in range(cols):
            index = row * cols + col
            char = ramp[min(last, luminances[index] * len(ramp) // 256)]
            red, green, blue = colours[index]
            cells.append((char, f"#{red:02x}{green:02x}{blue:02x}"))
        grid.append(cells)
    return grid
