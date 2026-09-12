from datetime import datetime, timezone

from generator.stats import Language, fetch_languages, fetch_profile, uptime


class FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def graphql(self, query, **variables):
        return self.payload


PROFILE_PAYLOAD = {
    "user": {
        "createdAt": "2016-07-31T22:07:19Z",
        "followers": {"totalCount": 768},
        "repositories": {
            "totalCount": 95,
            "nodes": [
                {"stargazerCount": 20000, "forkCount": 3000},
                {"stargazerCount": 471, "forkCount": 104},
            ],
        },
        "contributionsCollection": {"totalCommitContributions": 434},
    }
}


def test_profile_sums_stars_and_forks():
    profile = fetch_profile(FakeClient(PROFILE_PAYLOAD), "someone")
    assert profile.stars == 20471
    assert profile.forks == 3104
    assert profile.repos == 95
    assert profile.followers == 768
    assert profile.commits == 434


def test_profile_parses_creation_timestamp():
    profile = fetch_profile(FakeClient(PROFILE_PAYLOAD), "someone")
    assert profile.created_at.year == 2016


def test_uptime_renders_years_and_months():
    created = datetime(2016, 7, 31, tzinfo=timezone.utc)
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    assert uptime(created, now) == "10 years, 1 month"


def test_uptime_uses_singular_for_one():
    created = datetime(2025, 8, 12, tzinfo=timezone.utc)
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    assert uptime(created, now) == "1 year, 1 month"


LANG_PAYLOAD = {
    "user": {
        "repositories": {
            "nodes": [
                {"languages": {"edges": [
                    {"size": 600, "node": {"name": "Python", "color": "#3572A5"}},
                    {"size": 300, "node": {"name": "Java", "color": "#b07219"}},
                ]}},
                {"languages": {"edges": [
                    {"size": 100, "node": {"name": "Python", "color": "#3572A5"}},
                ]}},
            ]
        }
    }
}


def test_languages_are_byte_weighted_and_sorted():
    langs = fetch_languages(FakeClient(LANG_PAYLOAD), "someone", top=2)
    assert [l.name for l in langs] == ["Python", "Java"]
    assert round(langs[0].pct, 1) == 70.0
    assert round(langs[1].pct, 1) == 30.0


def test_language_without_colour_falls_back_to_dim():
    payload = {"user": {"repositories": {"nodes": [
        {"languages": {"edges": [{"size": 10, "node": {"name": "q", "color": None}}]}}
    ]}}}
    langs = fetch_languages(FakeClient(payload), "someone", top=1)
    assert langs[0].colour.startswith("#")


def test_no_languages_returns_empty_list():
    payload = {"user": {"repositories": {"nodes": []}}}
    assert fetch_languages(FakeClient(payload), "someone") == []
