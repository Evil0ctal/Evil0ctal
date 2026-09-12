"""Contribution calendar -> levelled grid and a snake traversal. No SVG here."""
from generator import config

CALENDAR_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount weekday } }
      }
    }
  }
}
"""


def fetch_counts(client, username: str) -> list[list[int]]:
    """Return contribution counts as [weekday][week]."""
    data = client.graphql(CALENDAR_QUERY, login=username)
    weeks = data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    grid = [[0] * len(weeks) for _ in range(config.CONTRIB_ROWS)]
    for week_index, week in enumerate(weeks):
        for day in week["contributionDays"]:
            grid[day["weekday"]][week_index] = day["contributionCount"]
    return grid


def _quantile(sorted_values: list[int], q: float) -> float:
    if not sorted_values:
        return 0.0
    position = (len(sorted_values) - 1) * q
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def bucket_levels(counts: list[list[int]]) -> list[list[int]]:
    """Map counts to levels 0-4 using quantiles of the non-zero days.

    A linear scale is wrong here: a single outlier day (148 against a median
    near 3 on this account) would drag every ordinary day into the lowest
    bucket. Quantiles reproduce GitHub's own visual weighting.
    """
    non_zero = sorted(value for row in counts for value in row if value > 0)
    if not non_zero:
        return [[0] * len(row) for row in counts]

    thresholds = [_quantile(non_zero, q) for q in config.BUCKET_QUANTILES]

    levels = []
    for row in counts:
        levelled = []
        for value in row:
            if value <= 0:
                levelled.append(0)
                continue
            level = 1
            for threshold in thresholds:
                if value > threshold:
                    level += 1
            levelled.append(min(level, len(config.CONTRIB_COLORS) - 1))
        levels.append(levelled)
    return levels


def snake_path(rows: int, cols: int) -> list[tuple[int, int]]:
    """Boustrophedon traversal: down the first column, up the next, and so on."""
    if rows <= 0 or cols <= 0:
        raise ValueError("rows and cols must be positive")
    path: list[tuple[int, int]] = []
    for col in range(cols):
        order = range(rows) if col % 2 == 0 else range(rows - 1, -1, -1)
        path.extend((row, col) for row in order)
    return path
