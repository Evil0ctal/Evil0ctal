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
