from PIL import Image
import pytest

from generator import config
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


def test_black_image_maps_to_first_ramp_character():
    grid = build_grid(solid((0, 0, 0)), cols=8)
    assert {cell[0] for row in grid for cell in row} == {config.ASCII_RAMP[0]}


def test_white_image_maps_to_last_ramp_character():
    grid = build_grid(solid((255, 255, 255)), cols=8)
    assert {cell[0] for row in grid for cell in row} == {config.ASCII_RAMP[-1]}


def test_cell_colour_is_lowercase_hex():
    grid = build_grid(solid((255, 0, 0)), cols=8)
    colour = grid[0][0][1]
    assert colour.startswith("#") and len(colour) == 7
    assert colour == colour.lower()


def test_real_avatar_produces_non_uniform_output():
    grid = build_grid(Image.open("tests/fixtures/avatar.png"), cols=40)
    chars = {cell[0] for row in grid for cell in row}
    assert len(chars) > 4, "a real photo should use several ramp levels"


def test_zero_columns_is_rejected():
    with pytest.raises(ValueError):
        build_grid(solid((0, 0, 0)), cols=0)
