import pytest

from generator.calendar import bucket_levels, fetch_counts, snake_path


class FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def graphql(self, query, **variables):
        return self.payload


def calendar_payload(weeks):
    return {"user": {"contributionsCollection": {"contributionCalendar": {
        "totalContributions": sum(sum(w) for w in weeks),
        "weeks": [
            {"contributionDays": [
                {"date": "2026-01-01", "contributionCount": c, "weekday": i}
                for i, c in enumerate(week)
            ]} for week in weeks
        ],
    }}}}


def test_fetch_counts_transposes_to_seven_rows():
    counts = fetch_counts(FakeClient(calendar_payload([[1, 2, 3, 4, 5, 6, 7]] * 3)), "x")
    assert len(counts) == 7
    assert all(len(row) == 3 for row in counts)
    assert counts[0] == [1, 1, 1]
    assert counts[6] == [7, 7, 7]


def test_zero_days_always_map_to_level_zero():
    levels = bucket_levels([[0, 5, 0], [0, 0, 9]])
    assert levels[0][0] == 0 and levels[0][2] == 0
    assert levels[1][0] == 0 and levels[1][1] == 0


def test_bucketing_is_quantile_based_not_linear():
    # One 148 outlier against a cluster of small values. Linear scaling would
    # push every small value into level 1; quantiles must spread them out.
    row = [1, 2, 3, 4, 5, 6, 7, 8, 148]
    levels = bucket_levels([row])[0]
    assert levels[-1] == 4, "the outlier belongs in the top bucket"
    assert len(set(levels[:-1])) > 1, "small values must not collapse into one level"


def test_all_equal_non_zero_values_share_a_level():
    levels = bucket_levels([[5, 5, 5, 5]])[0]
    assert len(set(levels)) == 1
    assert levels[0] >= 1


def test_empty_calendar_is_all_zero():
    assert bucket_levels([[0, 0], [0, 0]]) == [[0, 0], [0, 0]]


def test_snake_path_visits_every_cell_exactly_once():
    path = snake_path(7, 53)
    assert len(path) == 7 * 53
    assert len(set(path)) == 7 * 53


def test_snake_path_is_contiguous():
    path = snake_path(7, 5)
    for (r1, c1), (r2, c2) in zip(path, path[1:]):
        assert abs(r1 - r2) + abs(c1 - c2) == 1, f"jump between {(r1, c1)} and {(r2, c2)}"


def test_snake_path_serpentines_by_column():
    path = snake_path(3, 2)
    assert path[:3] == [(0, 0), (1, 0), (2, 0)]
    assert path[3:] == [(2, 1), (1, 1), (0, 1)]


def test_snake_path_rejects_empty_grid():
    with pytest.raises(ValueError):
        snake_path(0, 5)
