"""The only module that emits SVG. Everything reaching it is already computed."""
from dataclasses import dataclass
from datetime import datetime, timezone

from generator import config
from generator.stats import uptime


@dataclass(frozen=True)
class InfoMetrics:
    """What the info panel actually consumed, measured as it was rendered.

    Nothing downstream may re-derive these from a literal row count: the
    panel's height is a function of how many stats, sites, languages and
    wrapped value lines it emitted, all of which change when `config` does.

    * `last_baseline` - y of the panel's final baseline. `build_svg` starts
      the contribution graph below this, so a new stat row pushes the graph
      down instead of silently overprinting it.
    * `width_chars` - the widest row, in characters (key column included).
    * `right_edge` - where that widest row ends in px, measured at the
      pessimistic `config.LAYOUT_ADVANCE_W`. Must stay inside
      `config.CARD_WIDTH` or the row renders clipped.
    """
    last_baseline: float
    width_chars: int
    right_edge: float


def info_value_width(x: float) -> int:
    """How many characters of *value* fit on one info row starting at `x`.

    Derived from the canvas width rather than tuned to any one value, so
    editing `config.FOCUS` re-wraps instead of overflowing the card.
    """
    usable = config.CARD_WIDTH - config.PAD - x
    return max(1, int(usable // config.LAYOUT_ADVANCE_W) - config.INFO_KEY_WIDTH)


def wrap_value(value: str, width: int) -> list[str]:
    """Greedy whitespace wrap that drops nothing and never truncates.

    A separator token (`config.WRAP_SEPARATORS`) is never left trailing a
    line: it introduces the item after it, so it is carried onto the next
    line instead. A single token longer than `width` is emitted intact and
    overflows on purpose - losing characters from a value that renders as
    authoritative is worse than a visibly too-wide row, and
    `test_widest_info_row_fits_the_canvas` fails loudly if it happens.
    """
    if len(value) <= width:
        return [value]  # verbatim: never re-space a value that already fits

    tokens = value.split()
    if not tokens:
        return [value]

    lines: list[str] = []
    current: list[str] = []
    for token in tokens:
        if current and len(" ".join(current + [token])) > width:
            carry: list[str] = []
            while len(current) > 1 and current[-1] in config.WRAP_SEPARATORS:
                carry.insert(0, current.pop())
            lines.append(" ".join(current))
            current = carry
        current.append(token)
    if current:
        lines.append(" ".join(current))
    return lines


def escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def colour_runs(row) -> list[tuple[str, str]]:
    """Merge neighbouring cells that share a colour.

    Without this a 40x20 coloured portrait needs 800 elements; with it the
    same portrait lands around 28 KB.
    """
    runs: list[tuple[str, str]] = []
    for char, colour in row:
        if runs and runs[-1][1] == colour:
            runs[-1] = (runs[-1][0] + char, colour)
        else:
            runs.append((char, colour))
    return runs


def render_portrait(grid, x: float, y: float) -> str:
    parts = [f'<text x="{x}" y="{y}">']
    for index, row in enumerate(grid):
        parts.append(f'<tspan x="{x}" y="{y + index * config.CELL_H:.1f}">')
        for text, colour in colour_runs(row):
            parts.append(f'<tspan fill="{colour}">{escape(text)}</tspan>')
        parts.append("</tspan>")
    parts.append("</text>")
    return "".join(parts)


def _row(x: float, y: float, key: str, value: str, key_colour: str) -> str:
    return (f'<tspan x="{x}" y="{y:.1f}">'
            f'<tspan fill="{key_colour}" font-weight="bold">'
            f'{escape(key):<{config.INFO_KEY_WIDTH}}</tspan>'
            f'<tspan fill="{config.FG}">{escape(value)}</tspan></tspan>')


def _link_row(x: float, y: float, key: str, label: str, href: str) -> str:
    """A key/value row that is itself a clickable link.

    Unlike `_row`, this returns a *self-contained* element: the whole thing
    is one `<text>` wrapped in a single `<a>`, so both the key and the value
    are part of the link and nothing here needs (or is allowed) to live
    outside a `<text>` ancestor. Callers must not splice this into another
    open `<text>`/`<tspan>` run — it stands on its own alongside other
    top-level `<text>` elements.
    """
    return (f'<a href="{escape(href)}">'
            f'<text x="{x}" y="{y:.1f}">'
            f'<tspan fill="{config.KEY_COLOR}" font-weight="bold">'
            f'{escape(key):<{config.INFO_KEY_WIDTH}}</tspan>'
            f'<tspan fill="{config.ACCENT}">{escape(label)}</tspan>'
            f'</text></a>')


def render_info(profile, languages, loc, x: float, y: float, now) -> tuple[str, InfoMetrics]:
    """Render the neofetch-style info panel.

    Most rows are plain `<tspan>`s and are batched into shared `<text>`
    elements. Link rows (`_link_row`) are self-contained `<a><text>...
    </text></a>` fragments and must sit *outside* any other `<text>` — so
    whenever a link row is due, the current batch of tspans is flushed into
    its own `<text>` element first, the link is appended as its own
    top-level element, and a fresh batch starts afterwards. This keeps every
    `<tspan>` inside a `<text>` ancestor, which is what makes it render.

    Long values are wrapped onto continuation rows (blank key column, the
    way a terminal wraps an over-long neofetch field) at a width derived
    from the canvas — so editing `config.FOCUS` can never push the row off
    the right edge of the card.

    Returns the markup *and* an `InfoMetrics` recording the extent it
    actually used. `build_svg` places the contribution graph from that
    measurement rather than from a hardcoded row count, so this function
    stays the single owner of how tall and wide the panel is.
    """
    parts: list[str] = []
    buffer: list[str] = []
    cursor = y
    widths: list[int] = []
    value_width = info_value_width(x)

    def flush() -> None:
        if buffer:
            parts.append(f'<text x="{x}" y="{y}">' + "".join(buffer) + "</text>")
            buffer.clear()

    banner = f"{config.USERNAME}@github"
    widths.append(len(banner))
    buffer.append(f'<tspan x="{x}" y="{cursor:.1f}" fill="{config.ACCENT}" '
                  f'font-weight="bold">{escape(banner)}</tspan>')
    cursor += config.CELL_H
    widths.append(config.INFO_SEPARATOR_WIDTH)
    buffer.append(f'<tspan x="{x}" y="{cursor:.1f}" fill="{config.DIM}">'
                  f'{"─" * config.INFO_SEPARATOR_WIDTH}</tspan>')
    cursor += config.CELL_H

    loc_text = f"+{loc.additions:,} / -{loc.deletions:,}"
    if loc.stale:
        loc_text += "  (cached)"

    rows = [
        ("OS", config.OS_LINE, config.ACCENT),
        ("Shell", config.SHELL_LINE, config.ACCENT),
        ("Uptime", uptime(profile.created_at, now), config.ACCENT),
        ("Repos", f"{profile.repos:,} {config.REPO_COUNT_SUFFIX}", config.KEY_COLOR),
        ("Stars", f"{profile.stars:,}", config.STAR_COLOR),
        ("Forks", f"{profile.forks:,}", config.KEY_COLOR),
        ("Followers", f"{profile.followers:,}", config.KEY_COLOR),
        ("Commits", f"{profile.commits:,} {config.COMMITS_LABEL}", config.KEY_COLOR),
        ("Lines", loc_text, config.KEY_COLOR),
        ("Focus", config.FOCUS, config.ACCENT),
    ]
    for key, value, colour in rows:
        for index, line in enumerate(wrap_value(value, value_width)):
            widths.append(config.INFO_KEY_WIDTH + len(line))
            buffer.append(_row(x, cursor, key if index == 0 else "", line, colour))
            cursor += config.CELL_H

    # Link rows are self-contained <a><text>...</text></a> elements, not
    # tspans — flush the batched rows above into their own <text> before
    # appending each link as its own top-level element.
    flush()
    for label, href in config.SITES:
        widths.append(config.INFO_KEY_WIDTH + len(label))
        parts.append(_link_row(x, cursor, "Site", label, href))
        cursor += config.CELL_H
    widths.append(config.INFO_KEY_WIDTH + len(config.EMAIL))
    parts.append(_link_row(x, cursor, "Contact", config.EMAIL, f"mailto:{config.EMAIL}"))
    cursor += config.CELL_H

    widths.append(config.INFO_SEPARATOR_WIDTH)
    buffer.append(f'<tspan x="{x}" y="{cursor:.1f}" fill="{config.DIM}">'
                  f'{"─" * config.INFO_SEPARATOR_WIDTH}</tspan>')
    cursor += config.CELL_H

    for language in languages:
        filled = round(language.pct / 100 * config.LANG_BAR_CELLS)
        bar = "█" * filled + "░" * (config.LANG_BAR_CELLS - filled)
        name = language.name[:config.LANG_NAME_MAX_CHARS]
        percent = f" {language.pct:4.1f}%"
        widths.append(config.INFO_KEY_WIDTH + len(bar) + len(percent))
        colour = escape(language.colour)  # external data (GraphQL `color` field) — never trust it raw
        buffer.append(
            f'<tspan x="{x}" y="{cursor:.1f}">'
            f'<tspan fill="{colour}">{escape(name):<{config.INFO_KEY_WIDTH}}</tspan>'
            f'<tspan fill="{colour}">{bar}</tspan>'
            f'<tspan fill="{config.FG}">{percent}</tspan></tspan>')
        cursor += config.CELL_H

    cursor += config.CELL_H * 0.4
    swatch_cells = ["███"] * len(config.SWATCH)
    widths.append(sum(len(cell) for cell in swatch_cells))
    swatch = "".join(f'<tspan fill="{colour}">{cell}</tspan>'
                     for colour, cell in zip(config.SWATCH, swatch_cells))
    buffer.append(f'<tspan x="{x}" y="{cursor:.1f}">{swatch}</tspan>')

    flush()
    width_chars = max(widths)
    metrics = InfoMetrics(
        last_baseline=cursor,
        width_chars=width_chars,
        right_edge=x + width_chars * config.LAYOUT_ADVANCE_W,
    )
    return "".join(parts), metrics


def build_svg(grid, profile, languages, levels, loc, path=None, now=None) -> str:
    now = now or datetime.now(timezone.utc)

    portrait_x = config.PAD
    info_x = config.PAD + len(grid[0]) * config.CELL_W + config.COLUMN_GAP
    body_top = config.BODY_TOP

    portrait = render_portrait(grid, portrait_x, body_top)
    info, info_metrics = render_info(profile, languages, loc, info_x, body_top, now)

    from generator.render_contrib import render_contributions  # Task 7
    # The graph starts below whichever column is taller, measured — never a
    # literal row count. A hardcoded 20 used to sit above the info panel's
    # real 22 rows, so the first grid row overprinted the colour swatch.
    portrait_last_baseline = body_top + (len(grid) - 1) * config.CELL_H
    body_last_baseline = max(portrait_last_baseline, info_metrics.last_baseline)
    graph_y = body_last_baseline + config.CELL_H * (1 + config.GRAPH_GAP_ROWS)
    graph, graph_h = render_contributions(levels, path, config.PAD, graph_y)

    height = graph_y + graph_h + config.PAD
    width = config.CARD_WIDTH

    dots = "".join(
        f'<circle cx="{dot_x}" cy="{config.TITLEBAR_DOT_Y}" '
        f'r="{config.TITLEBAR_DOT_RADIUS}" fill="{colour}"/>'
        for dot_x, colour in zip(config.TITLEBAR_DOT_X, config.TITLEBAR_DOT_COLORS)
    )
    caption = escape(config.USERNAME.lower() + config.TITLEBAR_CAPTION_SUFFIX)

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width}" height="{height:.0f}" viewBox="0 0 {width} {height:.0f}" '
        f'font-family="ui-monospace,SFMono-Regular,Consolas,Menlo,monospace" '
        f'font-size="{config.FONT_SIZE}px">'
        f'<style>text,tspan{{white-space:pre}}</style>'
        f'<rect width="{width}" height="{height:.0f}" fill="{config.BG}" rx="{config.CARD_RADIUS}"/>'
        f'<rect width="{width}" height="{config.TITLEBAR_H}" fill="{config.TITLEBAR_OVERLAY}" '
        f'rx="{config.CARD_RADIUS}"/>'
        f'{dots}'
        f'<text x="{width / 2}" y="{config.TITLEBAR_CAPTION_Y}" fill="{config.DIM}" '
        f'text-anchor="middle" font-size="{config.TITLEBAR_FONT_SIZE}px">{caption}</text>'
        f'{portrait}{info}{graph}</svg>'
    )
