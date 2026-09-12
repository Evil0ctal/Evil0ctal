"""The only module that emits SVG. Everything reaching it is already computed."""
from datetime import datetime, timezone

from generator import config
from generator.stats import uptime


def escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


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


def render_info(profile, languages, loc, x: float, y: float, now) -> str:
    """Render the neofetch-style info panel.

    Most rows are plain `<tspan>`s and are batched into shared `<text>`
    elements. Link rows (`_link_row`) are self-contained `<a><text>...
    </text></a>` fragments and must sit *outside* any other `<text>` — so
    whenever a link row is due, the current batch of tspans is flushed into
    its own `<text>` element first, the link is appended as its own
    top-level element, and a fresh batch starts afterwards. This keeps every
    `<tspan>` inside a `<text>` ancestor, which is what makes it render.
    """
    parts: list[str] = []
    buffer: list[str] = []
    cursor = y

    def flush() -> None:
        if buffer:
            parts.append(f'<text x="{x}" y="{y}">' + "".join(buffer) + "</text>")
            buffer.clear()

    buffer.append(f'<tspan x="{x}" y="{cursor:.1f}" fill="{config.ACCENT}" '
                  f'font-weight="bold">{escape(config.USERNAME)}@github</tspan>')
    cursor += config.CELL_H
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
        ("Repos", f"{profile.repos:,} public", config.KEY_COLOR),
        ("Stars", f"{profile.stars:,}", config.STAR_COLOR),
        ("Forks", f"{profile.forks:,}", config.KEY_COLOR),
        ("Followers", f"{profile.followers:,}", config.KEY_COLOR),
        ("Commits", f"{profile.commits:,} this year", config.KEY_COLOR),
        ("Lines", loc_text, config.KEY_COLOR),
        ("Focus", config.FOCUS, config.ACCENT),
    ]
    for key, value, colour in rows:
        buffer.append(_row(x, cursor, key, value, colour))
        cursor += config.CELL_H

    # Link rows are self-contained <a><text>...</text></a> elements, not
    # tspans — flush the batched rows above into their own <text> before
    # appending each link as its own top-level element.
    flush()
    for label, href in config.SITES:
        parts.append(_link_row(x, cursor, "Site", label, href))
        cursor += config.CELL_H
    parts.append(_link_row(x, cursor, "Contact", config.EMAIL, f"mailto:{config.EMAIL}"))
    cursor += config.CELL_H

    buffer.append(f'<tspan x="{x}" y="{cursor:.1f}" fill="{config.DIM}">'
                  f'{"─" * config.INFO_SEPARATOR_WIDTH}</tspan>')
    cursor += config.CELL_H

    for language in languages:
        filled = round(language.pct / 100 * config.LANG_BAR_CELLS)
        bar = "█" * filled + "░" * (config.LANG_BAR_CELLS - filled)
        name = language.name[:config.LANG_NAME_MAX_CHARS]
        buffer.append(
            f'<tspan x="{x}" y="{cursor:.1f}">'
            f'<tspan fill="{language.colour}">{escape(name):<{config.INFO_KEY_WIDTH}}</tspan>'
            f'<tspan fill="{language.colour}">{bar}</tspan>'
            f'<tspan fill="{config.FG}"> {language.pct:4.1f}%</tspan></tspan>')
        cursor += config.CELL_H

    cursor += config.CELL_H * 0.4
    swatch = "".join(f'<tspan fill="{colour}">███</tspan>' for colour in config.SWATCH)
    buffer.append(f'<tspan x="{x}" y="{cursor:.1f}">{swatch}</tspan>')

    flush()
    return "".join(parts)


def build_svg(grid, profile, languages, levels, loc, path=None, now=None) -> str:
    now = now or datetime.now(timezone.utc)

    portrait_x = config.PAD
    info_x = config.PAD + len(grid[0]) * config.CELL_W + config.COLUMN_GAP
    body_top = config.BODY_TOP

    portrait = render_portrait(grid, portrait_x, body_top)
    info = render_info(profile, languages, loc, info_x, body_top, now)

    from generator.render_contrib import render_contributions  # Task 7
    graph_y = body_top + max(len(grid), 20) * config.CELL_H + config.CELL_H
    graph, graph_h = render_contributions(levels, path, config.PAD, graph_y)

    height = graph_y + graph_h + config.PAD
    width = config.CARD_WIDTH

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width}" height="{height:.0f}" viewBox="0 0 {width} {height:.0f}" '
        f'font-family="ui-monospace,SFMono-Regular,Consolas,Menlo,monospace" '
        f'font-size="{config.FONT_SIZE}px">'
        f'<style>text,tspan{{white-space:pre}}</style>'
        f'<rect width="{width}" height="{height:.0f}" fill="{config.BG}" rx="12"/>'
        f'<rect width="{width}" height="{config.TITLEBAR_H}" fill="#00000033" rx="12"/>'
        f'<circle cx="22" cy="17" r="6" fill="#ff5f57"/>'
        f'<circle cx="42" cy="17" r="6" fill="#febc2e"/>'
        f'<circle cx="62" cy="17" r="6" fill="#28c840"/>'
        f'<text x="{width / 2}" y="22" fill="{config.DIM}" text-anchor="middle" '
        f'font-size="12px">{escape(config.USERNAME.lower())} — neofetch</text>'
        f'{portrait}{info}{graph}</svg>'
    )
