import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from generator import config
from generator.calendar import snake_path
from generator.loc import LocTotals
from generator.render import (
    InfoMetrics, build_svg, colour_runs, escape, render_info, wrap_value,
)
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
PATH = snake_path(len(LEVELS), len(LEVELS[0]))


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
    markup, _ = render_info(PROFILE, LANGS, LOC, x=0, y=0, now=NOW)
    assert "21,734" in markup
    assert "3,104" in markup
    assert "768" in markup
    assert "434" in markup


def test_info_panel_renders_loc_with_signs():
    markup, _ = render_info(PROFILE, LANGS, LOC, x=0, y=0, now=NOW)
    assert "+120,000" in markup
    assert "-45,000" in markup


def test_stale_loc_is_marked():
    markup, _ = render_info(PROFILE, LANGS, LocTotals(1, 2, stale=True), x=0, y=0, now=NOW)
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
    markup, _ = render_info(PROFILE, [Language("Python", 100.0, "#3572A5")],
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
    markup, _ = render_info(PROFILE, LANGS, LOC, x=0, y=0, now=NOW)
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


# --- Final review coverage: F2 (the Focus row overflowed the canvas) ---

def info_x() -> float:
    """Where the info column really starts on the shipped card: the portrait
    is config.AVATAR_COLS wide, so this is what build_svg computes."""
    return config.PAD + config.AVATAR_COLS * config.CELL_W + config.COLUMN_GAP


def widest_info_row(focus=None, monkeypatch=None) -> InfoMetrics:
    if focus is not None:
        monkeypatch.setattr(config, "FOCUS", focus)
    _, metrics = render_info(PROFILE, LANGS, LOC, x=info_x(), y=config.BODY_TOP, now=NOW)
    return metrics


def test_widest_info_row_fits_the_canvas():
    """F2: the Focus row ran to 76 characters from x=388, ending at ~1026px
    against a 1000px canvas — it rendered clipped mid-word, and nothing
    checked the longest row against CARD_WIDTH.

    Measured at config.LAYOUT_ADVANCE_W, which is deliberately wider than
    both config.CELL_W (8.4) and the real monospace advance (~8.73-8.96), so
    passing here means fitting at any advance a real renderer picks.
    """
    metrics = widest_info_row()
    assert metrics.right_edge <= config.CARD_WIDTH, (
        f"widest info row is {metrics.width_chars} chars, ending at "
        f"{metrics.right_edge:.1f}px against a {config.CARD_WIDTH}px canvas"
    )


def test_widest_info_row_fits_at_both_plausible_advances():
    """The same guarantee spelled out at the two advances that matter: the
    config cell pitch, and a realistic ~9.0px monospace advance."""
    metrics = widest_info_row()
    for advance in (config.CELL_W, 9.0, config.LAYOUT_ADVANCE_W):
        right_edge = info_x() + metrics.width_chars * advance
        assert right_edge <= config.CARD_WIDTH, f"clipped at advance {advance}"


def test_editing_focus_rewraps_instead_of_overflowing(monkeypatch):
    """F2's regression guard: the fit must survive someone editing
    config.FOCUS, not just happen to hold for today's string."""
    metrics = widest_info_row(
        "reverse engineering · binary analysis · firmware · mobile security "
        "· web security · offensive tooling · protocol work · research", monkeypatch)
    assert metrics.right_edge <= config.CARD_WIDTH


def test_long_focus_is_wrapped_and_stays_legible(monkeypatch):
    """Wrapping, never truncation: every word of the value must still be on
    the card. A silently-cut value is exactly the class of defect this
    project refuses to ship."""
    focus = ("reverse engineering · binary analysis · firmware · mobile security "
             "· web security · offensive tooling")
    monkeypatch.setattr(config, "FOCUS", focus)
    markup, _ = render_info(PROFILE, LANGS, LOC, x=info_x(), y=config.BODY_TOP, now=NOW)
    for word in focus.split():
        assert escape(word) in markup, f"{word!r} was dropped from the Focus row"


def test_wrap_value_keeps_short_values_verbatim():
    assert wrap_value("+1,200 / -300  (cached)", 60) == ["+1,200 / -300  (cached)"]


def test_wrap_value_loses_nothing():
    lines = wrap_value(config.FOCUS, 30)
    assert " ".join(lines).split() == config.FOCUS.split()


def test_wrap_value_respects_the_width():
    for line in wrap_value(config.FOCUS, 30):
        assert len(line) <= 30


def test_wrap_value_never_leaves_a_separator_dangling():
    """A line ending in a lone "·" reads as a rendering accident; the
    separator introduces the item after it, so it travels with it."""
    for line in wrap_value(config.FOCUS, 53):
        assert line.split()[-1] not in config.WRAP_SEPARATORS


def test_wrap_value_handles_an_unsplittable_token():
    """A single token wider than the line is emitted intact — overflowing
    visibly beats dropping characters silently."""
    assert wrap_value("x" * 80, 10) == ["x" * 80]


# --- Final review coverage: F3 (hardcoded 20 info rows against a real 22) ---

def contribution_baselines(svg: str) -> list[float]:
    """Every contribution-cell baseline in a rendered card. Animated cells
    are the only <text> elements carrying the --lv custom property."""
    root = ET.fromstring(svg)
    return [float(element.get("y")) for element in root.iter()
            if element.tag.endswith("text") and "--lv" in (element.get("style") or "")]


def test_contribution_grid_starts_below_the_info_panel(monkeypatch):
    """F3: graph_y was `body_top + max(len(grid), 20) * CELL_H + CELL_H`, a
    bare literal duplicating a row count render_info itself owns. The panel
    is really 22+ rows, so the swatch sat at y=437.2 while the grid's first
    row started at y=430.0 and nine cells overprinted it.
    """
    monkeypatch.setattr(config, "SHOW_CONTRIBUTIONS", True)
    svg = build_svg(GRID, PROFILE, LANGS, LEVELS, LOC, path=PATH, now=NOW)
    _, metrics = render_info(PROFILE, LANGS, LOC, x=info_x(), y=config.BODY_TOP, now=NOW)
    baselines = contribution_baselines(svg)
    assert baselines, "expected animated contribution cells in the card"
    assert min(baselines) > metrics.last_baseline, (
        f"contribution grid starts at y={min(baselines)} but the info panel's "
        f"last baseline is y={metrics.last_baseline} — the grid overprints it"
    )


def test_adding_an_info_row_pushes_the_graph_down(monkeypatch):
    """The derivation must be live, not a literal that happens to be right
    today: one more language row must move the graph, not collide with it."""
    monkeypatch.setattr(config, "SHOW_CONTRIBUTIONS", True)
    def graph_top(langs):
        svg = build_svg(GRID, PROFILE, langs, LEVELS, LOC, path=PATH, now=NOW)
        return min(contribution_baselines(svg))

    extra = LANGS + [Language("Go", 5.0, "#00ADD8")]
    assert graph_top(extra) == graph_top(LANGS) + config.CELL_H


def test_card_height_covers_the_contribution_grid(monkeypatch):
    monkeypatch.setattr(config, "SHOW_CONTRIBUTIONS", True)
    svg = build_svg(GRID, PROFILE, LANGS, LEVELS, LOC, path=PATH, now=NOW)
    root = ET.fromstring(svg)
    height = float(root.get("height"))
    assert max(contribution_baselines(svg)) < height


# --- Final review coverage: F5 (the commit count was mislabelled) ---

def test_commit_count_is_labelled_last_twelve_months():
    """F5: `contributionsCollection` with no from/to covers the trailing
    twelve months, so "this year" was simply false."""
    markup, _ = render_info(PROFILE, LANGS, LOC, x=0, y=0, now=NOW)
    assert f"434 {config.COMMITS_LABEL}" in markup
    assert "this year" not in markup


def test_commit_label_lives_in_config():
    assert config.COMMITS_LABEL == "last 12 months"


def test_contribution_graph_can_be_switched_off(monkeypatch):
    """With SHOW_CONTRIBUTIONS off the card carries no grid and ends below the panel."""
    monkeypatch.setattr(config, "SHOW_CONTRIBUTIONS", False)
    svg = build_svg(GRID, PROFILE, LANGS, LEVELS, LOC, PATH, now=NOW)
    root = ET.fromstring(svg)
    assert "animation-delay" not in svg, "no snake animation when the graph is off"
    assert config.CONTRIB_CELL_CHAR not in svg, "no contribution cells when the graph is off"
    _, metrics = render_info(PROFILE, LANGS, LOC, 0, config.BODY_TOP, NOW)
    assert float(root.get("height")) > metrics.last_baseline, "card must still contain the panel"


def test_switching_the_graph_off_shortens_the_card(monkeypatch):
    monkeypatch.setattr(config, "SHOW_CONTRIBUTIONS", True)
    with_graph = float(ET.fromstring(
        build_svg(GRID, PROFILE, LANGS, LEVELS, LOC, PATH, now=NOW)).get("height"))
    monkeypatch.setattr(config, "SHOW_CONTRIBUTIONS", False)
    without = float(ET.fromstring(
        build_svg(GRID, PROFILE, LANGS, LEVELS, LOC, PATH, now=NOW)).get("height"))
    assert without < with_graph
