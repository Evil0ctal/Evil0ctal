from PIL import Image
import pytest

from generator import config
from generator import avatar
from generator.avatar import build_grid


def solid(colour, size=(80, 80)):
    return Image.new("RGB", size, colour)


def test_grid_has_requested_columns():
    grid = build_grid(solid((128, 128, 128)), cols=20)
    assert all(len(row) == 20 for row in grid)


def test_grid_rows_compensate_for_character_aspect():
    # square source, 20 cols -> 20 * 1.0 * 0.5 = 10 rows
    grid = build_grid(solid((128, 128, 128)), cols=20)
    assert len(grid) == 10


def test_black_image_maps_to_the_emptiest_glyph():
    """A flat dark cell has no ink, so the lightest-covering glyph must win."""
    grid = build_grid(solid((0, 0, 0)), cols=8)
    chars = {cell[0] for row in grid for cell in row}
    assert len(chars) == 1
    only = chars.pop()
    _, bitmaps = avatar._load_glyphs()
    coverage = bitmaps.mean(axis=1)
    lightest = avatar._load_glyphs()[0][int(coverage.argmin())]
    assert only == lightest


def test_white_image_covers_more_ink_than_black():
    """Whatever glyphs are chosen, a white field must carry more ink than black."""
    _, bitmaps = avatar._load_glyphs()
    chars, _ = avatar._load_glyphs()
    coverage = {ch: bitmaps[i].mean() for i, ch in enumerate(chars)}
    white = build_grid(solid((255, 255, 255)), cols=8)[0][0][0]
    black = build_grid(solid((0, 0, 0)), cols=8)[0][0][0]
    assert coverage[white] > coverage[black]


def test_cell_colour_is_lowercase_hex():
    grid = build_grid(solid((255, 0, 0)), cols=8)
    colour = grid[0][0][1]
    assert colour.startswith("#") and len(colour) == 7
    assert colour == colour.lower()


def test_real_avatar_produces_non_uniform_output():
    grid = build_grid(Image.open("tests/fixtures/avatar.png"), cols=40)
    chars = {cell[0] for row in grid for cell in row}
    assert len(chars) > 4, "a real photo should use many distinct glyphs"


def test_glyph_matching_uses_more_glyphs_than_a_ramp_has():
    """The point of glyph matching is a vocabulary wider than a 10-step ramp."""
    grid = build_grid(Image.open("tests/fixtures/avatar.png"), cols=56)
    chars = {cell[0] for row in grid for cell in row}
    assert len(chars) > len(config.ASCII_RAMP)


def test_glyph_table_is_self_consistent():
    chars, bitmaps = avatar._load_glyphs()
    cell_w, cell_h = config.GLYPH_CELL
    assert len(chars) == bitmaps.shape[0]
    assert bitmaps.shape[1] == cell_w * cell_h
    assert bitmaps.min() >= 0.0 and bitmaps.max() <= 1.0
    assert len(set(chars)) == len(chars), "duplicate glyphs waste scoring work"


def test_portrait_is_reproducible():
    """Same input, same output — the card must not drift between builds."""
    image = Image.open("tests/fixtures/avatar.png")
    assert build_grid(image, cols=32) == build_grid(image, cols=32)


def test_scoring_rejects_non_finite_values():
    import numpy as np
    import pytest as _pytest
    _, bitmaps = avatar._load_glyphs()
    poisoned = np.full((1, bitmaps.shape[1]), np.nan)
    with _pytest.raises(RuntimeError, match="non-finite"):
        avatar._score_cells(poisoned, bitmaps)


def test_zero_columns_is_rejected():
    with pytest.raises(ValueError):
        build_grid(solid((0, 0, 0)), cols=0)
