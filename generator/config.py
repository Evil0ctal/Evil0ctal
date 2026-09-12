"""Every tunable lives here. No logic, no imports from the rest of the package."""

USERNAME = "Evil0ctal"
USER_NODE_ID = "MDQ6VXNlcjIwNzYwNDQ4"
AVATAR_URL = "https://github.com/{user}.png?size={size}"
AVATAR_FETCH_SIZE = 460

# --- portrait ---
AVATAR_COLS = 40
ASCII_RAMP = " .:-=+*#%@"
CHAR_ASPECT = 0.5          # monospace cells are ~2x taller than wide
AUTOCONTRAST_CUTOFF = 2
CONTRAST_BOOST = 1.35

# --- geometry ---
CARD_WIDTH = 1000
CELL_W = 8.4
CELL_H = 18.0
FONT_SIZE = 14.5
PAD = 18
TITLEBAR_H = 34
BODY_TOP = 52
COLUMN_GAP = 34
# Advance width used for *fit* calculations only (never for positioning).
# CELL_W is the grid pitch the portrait is laid out on; the real advance of
# the monospace stack at FONT_SIZE measures ~8.73-8.96px depending on which
# face the viewer resolves. Wrapping and overflow checks use this
# deliberately pessimistic figure so a row that fits here also fits at any
# advance a real renderer picks.
LAYOUT_ADVANCE_W = 9.2
# Blank rows left between the portrait/info block and the contribution graph.
GRAPH_GAP_ROWS = 1.0
SHOW_CONTRIBUTIONS = False   # render the ASCII contribution graph + snake below the panel

# --- palette ---
BG = "#0d1117"
FG = "#c9d1d9"
DIM = "#4d5866"
ACCENT = "#7ee787"
KEY_COLOR = "#79c0ff"
STAR_COLOR = "#f0b72f"
ADD_COLOR = "#3fb950"
DEL_COLOR = "#f85149"
CONTRIB_COLORS = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]
SNAKE_COLOR = "#ffa657"
SWATCH = ["#ff5f57", "#febc2e", "#28c840", "#59a7ff", "#bd93f9", "#8be9fd", "#c9d1d9"]

# --- content ---
FOCUS = "full-stack · software RE · mobile RE · web RE · security research"
OS_LINE = "Darwin · Linux"
SHELL_LINE = "zsh · Python 3.13"
SITES = [("reer.dev", "https://reer.dev/"), ("gods.dev", "https://gods.dev/")]
EMAIL = "Evil0ctal1985@gmail.com"
TOP_LANGUAGES = 5
LANG_BAR_CELLS = 10
REPO_COUNT_SUFFIX = "sources"  # GitHub's own term for non-fork repos
# `contributionsCollection` with no from/to covers the TRAILING TWELVE
# MONTHS, not the calendar year -- the label has to say so.
COMMITS_LABEL = "last 12 months"

# --- info panel layout ---
INFO_SEPARATOR_WIDTH = 46   # dash count for the "─"*N separator rules
INFO_KEY_WIDTH = 11         # left-column width for key labels (e.g. "Repos")
LANG_NAME_MAX_CHARS = 10    # language name truncation, one char short of INFO_KEY_WIDTH
# Tokens that must never be left dangling at the end of a wrapped value:
# they introduce the item that follows, so they travel with it to the next
# line rather than trailing a line on their own.
WRAP_SEPARATORS = ("·", "-", "|", "/", ",", ";", "+", "&")

# --- window chrome (card frame + titlebar) ---
CARD_RADIUS = 12                       # corner radius shared by the card and titlebar rects
TITLEBAR_OVERLAY = "#00000033"         # translucent dark strip laid over the titlebar
TITLEBAR_DOT_COLORS = ("#ff5f57", "#febc2e", "#28c840")   # traffic-light dots, left to right
TITLEBAR_DOT_X = (22, 42, 62)          # x centre of each traffic-light dot, paired with the colours above
TITLEBAR_DOT_Y = 17                    # y centre shared by all three dots
TITLEBAR_DOT_RADIUS = 6
TITLEBAR_CAPTION_Y = 22                # baseline of the centred "user — neofetch" caption
TITLEBAR_FONT_SIZE = 12                # px, caption font size
TITLEBAR_CAPTION_SUFFIX = " — neofetch"

# --- contribution graph ---
CONTRIB_ROWS = 7
BUCKET_QUANTILES = [0.25, 0.50, 0.75, 0.90]
SNAKE_CYCLE_SECONDS = 12.0
CONTRIB_CELL_CHAR = "■"     # filled cell, levels 1-4
CONTRIB_EMPTY_CHAR = "·"    # level-0 (no contributions) cell
# @keyframes offsets (% of SNAKE_CYCLE_SECONDS) for the snake's head flash:
# holds the level colour, flashes to SNAKE_COLOR, drops to the empty
# colour and holds there before recovering to the level colour at 100%.
SNAKE_FLASH_PCT = 3
SNAKE_FADE_PCT = 6
SNAKE_HOLD_PCT = 55

# --- loc ---
LOC_CACHE_PATH = "cache/loc.json"
LOC_BUDGET_SECONDS = 240
LOC_PAGE_SIZE = 100
GITHUB_TIMEOUT_SECONDS = 30

OUTPUT_PATH = "profile.svg"
GITHUB_API = "https://api.github.com/graphql"
