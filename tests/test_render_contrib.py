import re
import xml.etree.ElementTree as ET

from generator import config
from generator.calendar import snake_path
from generator.render_contrib import render_contributions

LEVELS = [[(r + c) % 5 for c in range(53)] for r in range(7)]
PATH = snake_path(7, 53)


def wrap(markup):
    return ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{markup}</svg>')


def test_output_is_wellformed():
    markup, _ = render_contributions(LEVELS, PATH, 0, 0)
    wrap(markup)


def test_returns_positive_height():
    _, height = render_contributions(LEVELS, PATH, 0, 0)
    assert height > 0


def test_every_cell_gets_an_animation_delay():
    markup, _ = render_contributions(LEVELS, PATH, 0, 0)
    delays = re.findall(r"animation-delay:\s*([0-9.]+)s", markup)
    assert len(delays) == 7 * 53


def test_delays_are_ordered_along_the_snake_path():
    markup, _ = render_contributions(LEVELS, PATH, 0, 0)
    delays = [float(d) for d in re.findall(r"animation-delay:\s*([0-9.]+)s", markup)]
    assert delays == sorted(delays), "delays must increase along the path"


def test_cycle_length_matches_config():
    markup, _ = render_contributions(LEVELS, PATH, 0, 0)
    assert f"{config.SNAKE_CYCLE_SECONDS}s" in markup


def test_snake_colour_appears_in_keyframes():
    markup, _ = render_contributions(LEVELS, PATH, 0, 0)
    assert config.SNAKE_COLOR in markup


def test_level_colours_come_from_config():
    markup, _ = render_contributions(LEVELS, PATH, 0, 0)
    for colour in config.CONTRIB_COLORS:
        assert colour in markup


def test_works_without_a_path():
    markup, _ = render_contributions(LEVELS, None, 0, 0)
    wrap(markup)
    assert "animation-delay" not in markup, "no path means no snake"


# --- Final review coverage: the heat map's actual meaning ---

def parse_animated_cells(markup, x0=0.0, y0=0.0):
    """Map each animated cell back to the (row, col) it was drawn at.

    Cells are emitted in snake-path order, so position — not document order
    — is the only honest way to recover which grid cell a <text> represents.
    """
    cells = {}
    for element in wrap(markup).iter():
        if not element.tag.endswith("text"):
            continue
        style = element.get("style") or ""
        if "--lv" not in style:
            continue
        col = round((float(element.get("x")) - x0) / config.CELL_W)
        row = round((float(element.get("y")) - y0) / config.CELL_H)
        assert (row, col) not in cells, f"cell {(row, col)} was drawn twice"
        cells[(row, col)] = style
    return cells


def test_each_cell_is_painted_with_its_own_level_colour():
    """The heat map's entire meaning is the cell->level->colour binding.

    `test_level_colours_come_from_config` only asserts each palette colour
    appears *somewhere* in the markup, which would pass just as happily
    against code that handed every cell the wrong colour. This pins cell
    (r, c) to CONTRIB_COLORS[levels[r][c]] individually.
    """
    markup, _ = render_contributions(LEVELS, PATH, 0, 0)
    cells = parse_animated_cells(markup)
    assert len(cells) == 7 * 53, "every grid cell must be drawn exactly once"

    for row in range(7):
        for col in range(53):
            expected = config.CONTRIB_COLORS[LEVELS[row][col]]
            style = cells[(row, col)]
            assert f"--lv:{expected};" in style, (
                f"cell ({row}, {col}) is level {LEVELS[row][col]} and must "
                f"carry {expected}, got style {style!r}"
            )
            assert f"fill:{expected};" in style, (
                f"cell ({row}, {col}) must also *start* at its level colour"
            )


def test_each_cell_uses_the_character_for_its_level():
    """Level 0 is the empty glyph, every other level the filled one — the
    other half of the cell->level binding, and what carries the heat map
    for anyone reading the SVG as text."""
    markup, _ = render_contributions(LEVELS, PATH, 0, 0)
    for element in wrap(markup).iter():
        if not element.tag.endswith("text") or "--lv" not in (element.get("style") or ""):
            continue
        col = round(float(element.get("x")) / config.CELL_W)
        row = round(float(element.get("y")) / config.CELL_H)
        expected = (config.CONTRIB_EMPTY_CHAR if LEVELS[row][col] == 0
                    else config.CONTRIB_CELL_CHAR)
        assert element.text == expected, f"cell ({row}, {col}) drew {element.text!r}"


def test_static_fallback_also_binds_each_cell_to_its_level_colour():
    """The no-path fallback flows cells through shared <text> rows, so its
    binding is positional-by-order rather than by x/y — check it too."""
    markup, _ = render_contributions(LEVELS, None, 0, 0)
    rows = [element for element in wrap(markup).iter() if element.tag.endswith("tspan")
            and element.get("y") is not None]
    assert len(rows) == 7
    for row_index, row_element in enumerate(rows):
        colours = [cell.get("fill") for cell in row_element]
        assert colours == [config.CONTRIB_COLORS[level] for level in LEVELS[row_index]]
