"""ASCII contribution graph with a CSS-animated snake.

Replaces the Platane/snk action. Each cell is one character; the snake is a
staggered CSS animation rather than a pre-rendered sprite, so the whole thing
is a few kilobytes of text with no build-time dependency.

Mechanism: every animated cell carries its own level colour as the `--lv`
custom property plus an `animation-delay` proportional to its index along
the snake path. A single shared `@keyframes` rule briefly flashes a cell to
`config.SNAKE_COLOR`, drops it to the empty colour, then lets it recover to
`--lv`. Staggered across all cells by delay, that reads as a snake
travelling the grid. No SMIL, no JavaScript, no external action — GitHub's
`<img>` renderer honours CSS animations inside SVG, which is the same
mechanism Platane/snk relies on.

Cells are emitted in snake-path order (not row-major grid order) so that
`animation-delay` values appear in the markup in increasing order, matching
the order the snake actually travels. Each animated cell therefore needs an
explicit x/y (there is no shared row to flow characters across), unlike the
static, non-animated fallback which flows each grid row through a shared
`<text>`/`<tspan>` pair the way `render.render_portrait` does.
"""
from generator import config
from generator.render import escape


def render_contributions(levels, path, x: float, y: float) -> tuple[str, float]:
    rows = len(levels)
    cols = len(levels[0]) if rows else 0
    if not rows or not cols:
        return "", 0.0

    if path:
        if len(path) != rows * cols:
            raise ValueError(
                f"path must visit every cell exactly once: expected {rows * cols} "
                f"entries for a {rows}x{cols} grid, got {len(path)}"
            )
        markup = _render_animated(levels, path, x, y)
    else:
        markup = _render_static(levels, x, y)

    return markup, rows * config.CELL_H


def _cell_char(level: int) -> str:
    raw = config.CONTRIB_EMPTY_CHAR if level == 0 else config.CONTRIB_CELL_CHAR
    return escape(raw)


def _render_static(levels, x: float, y: float) -> str:
    """Flowing, non-animated fallback: one <text> per row, no snake path."""
    parts = [f'<text x="{x}" y="{y}">']
    for row_index, row in enumerate(levels):
        parts.append(f'<tspan x="{x}" y="{y + row_index * config.CELL_H:.1f}">')
        for level in row:
            colour = config.CONTRIB_COLORS[level]
            parts.append(f'<tspan fill="{colour}">{_cell_char(level)}</tspan>')
        parts.append("</tspan>")
    parts.append("</text>")
    return "".join(parts)


def _keyframes() -> str:
    empty_colour = config.CONTRIB_COLORS[0]
    return (
        f"@keyframes snake{{"
        f"0%,100%{{fill:var(--lv)}}"
        f"{config.SNAKE_FLASH_PCT}%{{fill:{config.SNAKE_COLOR}}}"
        f"{config.SNAKE_FADE_PCT}%{{fill:{empty_colour}}}"
        f"{config.SNAKE_HOLD_PCT}%{{fill:{empty_colour}}}"
        f"}}"
    )


def _render_animated(levels, path, x: float, y: float) -> str:
    """One independently positioned <text> per cell, emitted in path order.

    Emission order must match path order (not grid order) so that the
    `animation-delay` values increase monotonically as they appear in the
    markup — that ordering is how the staggered flash reads as a snake
    travelling the grid rather than a random flicker.
    """
    total = max(1, len(path))
    parts = [f"<style>{_keyframes()}</style>"]
    for index, (row_index, col_index) in enumerate(path):
        level = levels[row_index][col_index]
        colour = config.CONTRIB_COLORS[level]
        cell_x = x + col_index * config.CELL_W
        cell_y = y + row_index * config.CELL_H
        delay = index / total * config.SNAKE_CYCLE_SECONDS
        style = (
            f"--lv:{colour};fill:{colour};"
            f"animation:snake {config.SNAKE_CYCLE_SECONDS}s linear infinite;"
            f"animation-delay:{delay:.3f}s"
        )
        parts.append(
            f'<text x="{cell_x:.1f}" y="{cell_y:.1f}" style="{style}">{_cell_char(level)}</text>'
        )
    return "".join(parts)
