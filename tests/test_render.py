import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from generator import config
from generator.loc import LocTotals
from generator.render import build_svg, colour_runs, escape, render_info
from generator.stats import Language, Profile

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
PROFILE = Profile(
    created_at=datetime(2016, 7, 31, tzinfo=timezone.utc),
    followers=768, repos=95, stars=21734, forks=3104, commits=434,
)
LANGS = [Language("Python", 62.5, "#3572A5"), Language("Java", 12.0, "#b07219")]
LOC = LocTotals(additions=120000, deletions=45000, stale=False)
GRID = [[("@", "#ff0000"), ("@", "#ff0000"), (".", "#00ff00")]]
LEVELS = [[0, 1], [2, 3], [4, 0], [1, 1], [2, 2], [3, 3], [4, 4]]


def test_escape_handles_xml_metacharacters():
    assert escape("a & b < c > d") == "a &amp; b &lt; c &gt; d"


def test_colour_runs_merge_adjacent_identical_colours():
    runs = colour_runs([("a", "#111111"), ("b", "#111111"), ("c", "#222222")])
    assert runs == [("ab", "#111111"), ("c", "#222222")]


def test_colour_runs_on_empty_row():
    assert colour_runs([]) == []


def test_build_svg_is_wellformed_xml():
    svg = build_svg(GRID, PROFILE, LANGS, LEVELS, LOC, now=NOW)
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")


def test_build_svg_sets_configured_width():
    svg = build_svg(GRID, PROFILE, LANGS, LEVELS, LOC, now=NOW)
    assert ET.fromstring(svg).get("width") == str(config.CARD_WIDTH)


def test_info_panel_contains_live_numbers():
    markup = render_info(PROFILE, LANGS, LOC, x=0, y=0, now=NOW)
    assert "21,734" in markup
    assert "3,104" in markup
    assert "768" in markup
    assert "434" in markup


def test_info_panel_renders_loc_with_signs():
    markup = render_info(PROFILE, LANGS, LOC, x=0, y=0, now=NOW)
    assert "+120,000" in markup
    assert "-45,000" in markup


def test_stale_loc_is_marked():
    markup = render_info(PROFILE, LANGS, LocTotals(1, 2, stale=True), x=0, y=0, now=NOW)
    assert "cached" in markup


def test_sites_and_email_are_real_links():
    svg = build_svg(GRID, PROFILE, LANGS, LEVELS, LOC, now=NOW)
    root = ET.fromstring(svg)
    hrefs = {a.get("{http://www.w3.org/1999/xlink}href") or a.get("href")
             for a in root.iter() if a.tag.endswith("}a")}
    assert "https://reer.dev/" in hrefs
    assert "https://gods.dev/" in hrefs
    assert f"mailto:{config.EMAIL}" in hrefs


def test_focus_line_is_present():
    svg = build_svg(GRID, PROFILE, LANGS, LEVELS, LOC, now=NOW)
    assert "software RE" in svg


def test_ampersand_in_content_is_escaped(monkeypatch):
    monkeypatch.setattr(config, "FOCUS", "R&D")
    svg = build_svg(GRID, PROFILE, LANGS, LEVELS, LOC, now=NOW)
    ET.fromstring(svg)  # would raise if the & leaked through
    assert "R&amp;D" in svg


def test_language_bar_length_matches_config():
    markup = render_info(PROFILE, [Language("Python", 100.0, "#3572A5")],
                         LOC, x=0, y=0, now=NOW)
    assert "█" * config.LANG_BAR_CELLS in markup


def test_every_tspan_has_a_text_ancestor():
    """Regression test for a known-defect class: `render_info` used to
    splice link-row `<tspan>` fragments outside of any `<text>` element.
    That parses as well-formed XML (so a bare well-formedness check would
    not catch it) but a `<tspan>` without a `<text>` ancestor renders
    nothing — the key labels would silently vanish from the card.

    This walks the parsed tree and asserts every `<tspan>` has a `<text>`
    somewhere above it, which is what actually makes it visible.
    """
    markup = render_info(PROFILE, LANGS, LOC, x=0, y=0, now=NOW)
    root = ET.fromstring(f"<root>{markup}</root>")

    parent_of = {child: parent for parent in root.iter() for child in parent}

    def has_text_ancestor(element) -> bool:
        node = parent_of.get(element)
        while node is not None:
            if node.tag == "text":
                return True
            node = parent_of.get(node)
        return False

    tspans = [element for element in root.iter() if element.tag == "tspan"]
    assert tspans, "expected at least one tspan in the info panel"
    assert all(has_text_ancestor(tspan) for tspan in tspans)
