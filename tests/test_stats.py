import copy
from datetime import datetime, timezone

import pytest

from generator.stats import (
    LANGUAGE_QUERY, PROFILE_QUERY, Language, StatsError, fetch_languages, fetch_profile, uptime,
)


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


def test_languages_weight_every_repository_equally():
    """repo1 is 2/3 Python, repo2 is all Python -> (0.667 + 1.0) / 2 = 83.3%."""
    langs = fetch_languages(FakeClient(LANG_PAYLOAD), "someone", top=2)
    assert [l.name for l in langs] == ["Python", "Java"]
    assert round(langs[0].pct, 1) == 83.3
    assert round(langs[1].pct, 1) == 16.7


def test_one_huge_repository_cannot_dominate_the_mix():
    """The regression this weighting exists for.

    A single repo carrying a ~99 MB vendored WebAssembly blob was 89% of all
    bytes on the real account and rendered the card as "89.2% WebAssembly" for
    a developer with 22 Python repositories. One repo gets one vote.
    """
    payload = {"user": {"repositories": {
        "pageInfo": {"hasNextPage": False},
        "nodes": [
            {"languages": {"edges": [
                {"size": 99_000_000, "node": {"name": "WebAssembly", "color": "#04133b"}}]}},
            {"languages": {"edges": [
                {"size": 5_000, "node": {"name": "Python", "color": "#3572A5"}}]}},
            {"languages": {"edges": [
                {"size": 3_000, "node": {"name": "Python", "color": "#3572A5"}}]}},
        ]}}}
    langs = fetch_languages(FakeClient(payload), "someone", top=2)
    assert langs[0].name == "Python", "two small Python repos outvote one huge blob"
    assert round(langs[0].pct) == 67
    assert round(langs[1].pct) == 33


def test_repositories_with_no_code_are_not_counted():
    payload = {"user": {"repositories": {
        "pageInfo": {"hasNextPage": False},
        "nodes": [
            {"languages": {"edges": []}},
            {"languages": {"edges": [{"size": 10, "node": {"name": "Go", "color": "#00ADD8"}}]}},
        ]}}}
    langs = fetch_languages(FakeClient(payload), "someone", top=3)
    assert len(langs) == 1 and round(langs[0].pct) == 100, "an empty repo must not dilute the mix"


def test_language_without_colour_falls_back_to_dim():
    payload = {"user": {"repositories": {"nodes": [
        {"languages": {"edges": [{"size": 10, "node": {"name": "q", "color": None}}]}}
    ]}}}
    langs = fetch_languages(FakeClient(payload), "someone", top=1)
    assert langs[0].colour.startswith("#")


def test_no_languages_returns_empty_list():
    payload = {"user": {"repositories": {"nodes": []}}}
    assert fetch_languages(FakeClient(payload), "someone") == []


# --- Fix round 1 coverage (C1: private-repo leak) ---

def test_profile_query_excludes_private_repos():
    """C1: without a privacy filter, a broadly-scoped token pulls private
    repos into the public card's repo/star/fork counts."""
    assert "privacy: PUBLIC" in PROFILE_QUERY


def test_language_query_excludes_private_repos():
    assert "privacy: PUBLIC" in LANGUAGE_QUERY


# --- Final review coverage: F4 (repositories(first: 100) had no page guard) ---

def paged(payload, has_next_page):
    """Same payload, with the repository listing's pageInfo attached."""
    payload = copy.deepcopy(payload)
    payload["user"]["repositories"]["pageInfo"] = {"hasNextPage": has_next_page}
    return payload


def test_both_queries_request_the_listing_page_info():
    """F4: without pageInfo there is nothing to check. `totalCount` stays
    exact while stars, forks and the language mix are summed over at most
    100 nodes, so crossing 100 undercounts with the repo count still
    looking right."""
    for query in (PROFILE_QUERY, LANGUAGE_QUERY):
        assert "pageInfo { hasNextPage }" in query


def test_profile_fails_loudly_when_the_repo_listing_has_another_page():
    """A wrong number is worse than no number: past 100 public sources the
    star and fork totals must abort the build, not quietly undercount."""
    with pytest.raises(StatsError) as raised:
        fetch_profile(FakeClient(paged(PROFILE_PAYLOAD, True)), "someone")
    message = str(raised.value)
    assert "100" in message, "the error must name the limitation it hit"
    assert "undercount" in message


def test_languages_fail_loudly_when_the_repo_listing_has_another_page():
    with pytest.raises(StatsError) as raised:
        fetch_languages(FakeClient(paged(LANG_PAYLOAD, True)), "someone")
    assert "language mix" in str(raised.value)


def test_a_single_page_listing_is_summed_normally():
    """The guard must fire on hasNextPage only — a listing that fits in one
    page is exactly what the card is built from every day."""
    profile = fetch_profile(FakeClient(paged(PROFILE_PAYLOAD, False)), "someone")
    assert profile.stars == 20471
    langs = fetch_languages(FakeClient(paged(LANG_PAYLOAD, False)), "someone", top=2)
    assert [language.name for language in langs] == ["Python", "Java"]


def test_stats_error_is_catchable_as_a_runtime_error():
    """main() catches RuntimeError, so the loud failure becomes a clean
    non-zero exit rather than a raw traceback."""
    assert issubclass(StatsError, RuntimeError)
