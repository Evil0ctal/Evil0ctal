"""Avatar image -> grid of (character, colour) cells. Knows nothing about SVG.

Characters are chosen by matching each cell against pre-rendered glyph coverage
bitmaps rather than by indexing a brightness ramp. A ramp only knows how dark a
cell is; glyph matching also knows what SHAPE the ink in that cell makes, so an
eyebrow picks a horizontal stroke and a jawline picks a diagonal one.

The score deliberately blends two terms. Matching on mean-subtracted patches
alone — pure normalised correlation — throws away brightness and fits noise:
the first version of this produced confetti, not a face. Matching on tone alone
is just a ramp with extra steps. Tone leads, structure refines.
"""
import base64
import io
import json
import pathlib

import numpy as np
import requests
from PIL import Image, ImageOps

from generator import config

Cell = tuple[str, str]

_GLYPHS: tuple[tuple[str, ...], "np.ndarray"] | None = None


def _load_glyphs() -> tuple[tuple[str, ...], np.ndarray]:
    """Glyph coverage bitmaps, committed so output does not depend on host fonts.

    Rendering these at runtime would tie the portrait to whatever monospace font
    the machine happens to have, and a CI build would disagree with a local one.
    """
    global _GLYPHS
    if _GLYPHS is None:
        path = pathlib.Path(__file__).with_name(config.GLYPH_BITMAP_FILE)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError(f"Cannot read glyph bitmaps at {path}: {error}") from error
        width, height = doc["cell"]
        if [width, height] != list(config.GLYPH_CELL):
            raise RuntimeError(
                f"Glyph bitmap cell {width}x{height} does not match "
                f"config.GLYPH_CELL {config.GLYPH_CELL}")
        chars, rows = [], []
        for char, encoded in sorted(doc["glyphs"].items()):
            raw = base64.b64decode(encoded)
            if len(raw) != width * height:
                raise RuntimeError(f"Glyph {char!r} has {len(raw)} bytes, expected {width * height}")
            chars.append(char)
            rows.append(np.frombuffer(raw, dtype=np.uint8))
        if not chars:
            raise RuntimeError("Glyph bitmap file contains no glyphs")
        _GLYPHS = (tuple(chars), np.stack(rows).astype(np.float64) / 255.0)
    return _GLYPHS


def fetch_avatar(username: str, size: int = config.AVATAR_FETCH_SIZE) -> Image.Image:
    url = config.AVATAR_URL.format(user=username, size=size)
    response = requests.get(url, timeout=config.GITHUB_TIMEOUT_SECONDS)
    if response.status_code != 200:
        raise RuntimeError(f"Avatar fetch failed for {username}: HTTP {response.status_code}")
    return Image.open(io.BytesIO(response.content)).convert("RGB")


def _score_cells(patches: np.ndarray, bitmaps: np.ndarray) -> np.ndarray:
    """Index of the best-matching glyph for every cell, scored in one pass.

    Both terms reduce to a dot product, so the whole image is two matrix
    multiplies rather than a Python loop over cells x glyphs x pixels — which
    measured 32s for one portrait and would have cost that on every CI build.
    """
    per_cell = patches.shape[1]

    # NumPy's matmul goes through BLAS, which does not clear the FPU exception
    # flags, so a flag left dirty by an earlier operation gets reported against
    # the next matmul. Verified: after a deliberate 1/0, even
    # np.ones((4,4)) @ np.ones((4,4)) raises "divide by zero". Every input here
    # is finite and in [0, 1], so those warnings are stale, not ours. They are
    # suppressed, and the result is checked for real numerical failure below.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        dot = patches @ bitmaps.T
        tone_error = (np.sum(bitmaps ** 2, axis=1)[None, :]
                      - 2.0 * dot
                      + np.sum(patches ** 2, axis=1)[:, None]) / per_cell
        tone = 1.0 - tone_error / config.GLYPH_WORST_TONE_ERROR

        # Structure: normalised correlation of the mean-subtracted patterns.
        centred_glyphs = bitmaps - bitmaps.mean(axis=1, keepdims=True)
        centred_cells = patches - patches.mean(axis=1, keepdims=True)
        usable = np.outer(np.linalg.norm(centred_cells, axis=1),
                          np.linalg.norm(centred_glyphs, axis=1))
        safe = np.where(usable > 1e-12, usable, 1.0)
        structure = np.where(usable > 1e-12, (centred_cells @ centred_glyphs.T) / safe, 0.0)
        structure = (structure + 1.0) / 2.0

        weight = config.GLYPH_STRUCTURE_WEIGHT
        score = (1.0 - weight) * tone + weight * structure

    # A genuine NaN here would silently pick glyph 0 for every affected cell, so
    # it must fail loudly rather than render a corrupted portrait.
    if not np.isfinite(score).all():
        raise RuntimeError("Glyph scoring produced non-finite values; refusing to render")
    return np.argmax(score, axis=1)


def build_grid(image: Image.Image, cols: int = config.AVATAR_COLS) -> list[list[Cell]]:
    if cols <= 0:
        raise ValueError("cols must be positive")

    rgb = image.convert("RGB")
    width, height = rgb.size
    rows = max(1, round(cols * (height / width) * config.CHAR_ASPECT))

    chars, bitmaps = _load_glyphs()
    cell_w, cell_h = config.GLYPH_CELL

    # Sample luminance at glyph resolution, not one value per cell, so the
    # matcher can see how ink is distributed inside each cell.
    detail = ImageOps.autocontrast(rgb.convert("L"), cutoff=config.AUTOCONTRAST_CUTOFF)
    detail = detail.resize((cols * cell_w, rows * cell_h), Image.LANCZOS)
    pixels = np.asarray(detail, dtype=np.float64) / 255.0

    # (rows, cols, cell_h * cell_w), one flattened patch per character cell.
    patches = (pixels.reshape(rows, cell_h, cols, cell_w)
                     .transpose(0, 2, 1, 3)
                     .reshape(rows * cols, cell_h * cell_w))
    best = _score_cells(patches, bitmaps)

    colours = np.asarray(rgb.resize((cols, rows), Image.LANCZOS), dtype=int).reshape(-1, 3)

    grid: list[list[Cell]] = []
    for row in range(rows):
        cells: list[Cell] = []
        for col in range(cols):
            index = row * cols + col
            red, green, blue = colours[index]
            cells.append((chars[best[index]], f"#{red:02x}{green:02x}{blue:02x}"))
        grid.append(cells)
    return grid
