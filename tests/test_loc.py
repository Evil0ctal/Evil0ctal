import json

from generator.loc import LocTotals, compute, load_cache, save_cache


class ScriptedClient:
    """Returns queued payloads; records how many calls were made."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def graphql(self, query, **variables):
        self.calls += 1
        return self.payloads.pop(0)


def repo_payload(repos):
    return {"user": {"repositories": {
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "nodes": repos,
    }}}


def repo(name, head, commits, has_next_page=False, end_cursor=None):
    return {
        "nameWithOwner": name,
        "defaultBranchRef": {"target": {
            "oid": head,
            "history": {
                "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
                "nodes": commits,
            },
        }},
    }


def history_page(commits, has_next_page=False, end_cursor=None):
    """Payload shape returned by loc.HISTORY_QUERY for a single repo's next page."""
    return {"repository": {"defaultBranchRef": {"target": {"history": {
        "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
        "nodes": commits,
    }}}}}


def commit(oid, add, dele, date="2026-09-11T00:00:00Z"):
    return {"oid": oid, "additions": add, "deletions": dele, "committedDate": date}


def test_cache_roundtrip(tmp_path):
    path = tmp_path / "loc.json"
    save_cache(str(path), {"a/b": {"head": "x", "additions": 1, "deletions": 2}})
    assert load_cache(str(path))["a/b"]["head"] == "x"


def test_missing_cache_loads_as_empty(tmp_path):
    assert load_cache(str(tmp_path / "nope.json")) == {}


def test_unchanged_head_reuses_cached_totals(tmp_path):
    path = tmp_path / "loc.json"
    save_cache(str(path), {"u/r": {"head": "SAME", "last_date": "2026-01-01T00:00:00Z",
                                   "additions": 500, "deletions": 100, "oids": []}})
    client = ScriptedClient([repo_payload([repo("u/r", "SAME", [])])])
    totals = compute(client, "u", "NODE", str(path), budget_seconds=60)
    assert totals == LocTotals(additions=500, deletions=100, stale=False)


def test_changed_head_adds_new_commits_to_cached_totals(tmp_path):
    path = tmp_path / "loc.json"
    save_cache(str(path), {"u/r": {"head": "OLD", "last_date": "2026-01-01T00:00:00Z",
                                   "additions": 500, "deletions": 100, "oids": []}})
    client = ScriptedClient([
        repo_payload([repo("u/r", "NEW", [commit("c1", 10, 3), commit("c2", 5, 1)])])
    ])
    totals = compute(client, "u", "NODE", str(path), budget_seconds=60)
    assert totals.additions == 515
    assert totals.deletions == 104
    assert totals.stale is False


def test_already_counted_oids_are_not_double_counted(tmp_path):
    path = tmp_path / "loc.json"
    save_cache(str(path), {"u/r": {"head": "OLD", "last_date": "2026-09-11T00:00:00Z",
                                   "additions": 500, "deletions": 100, "oids": ["c1"]}})
    client = ScriptedClient([
        repo_payload([repo("u/r", "NEW", [commit("c1", 10, 3), commit("c2", 5, 1)])])
    ])
    totals = compute(client, "u", "NODE", str(path), budget_seconds=60)
    assert totals.additions == 505, "c1 was already counted"


def test_fresh_repo_counts_all_commits(tmp_path):
    client = ScriptedClient([
        repo_payload([repo("u/r", "HEAD", [commit("c1", 7, 2)])])
    ])
    totals = compute(client, "u", "NODE", str(tmp_path / "loc.json"), budget_seconds=60)
    assert totals.additions == 7 and totals.deletions == 2


def test_empty_default_branch_is_skipped(tmp_path):
    client = ScriptedClient([repo_payload([
        {"nameWithOwner": "u/empty", "defaultBranchRef": None}
    ])])
    totals = compute(client, "u", "NODE", str(tmp_path / "loc.json"), budget_seconds=60)
    assert totals == LocTotals(additions=0, deletions=0, stale=False)


def test_exhausted_budget_marks_result_stale(tmp_path):
    path = tmp_path / "loc.json"
    save_cache(str(path), {"u/r": {"head": "OLD", "last_date": "2026-01-01T00:00:00Z",
                                   "additions": 800, "deletions": 200, "oids": []}})
    client = ScriptedClient([repo_payload([repo("u/r", "NEW", [commit("c1", 1, 1)])])])
    totals = compute(client, "u", "NODE", str(path), budget_seconds=0)
    assert totals.stale is True
    assert totals.additions == 800, "falls back to the cached figure"


def test_cache_is_written_back(tmp_path):
    path = tmp_path / "loc.json"
    client = ScriptedClient([repo_payload([repo("u/r", "HEAD", [commit("c1", 7, 2)])])])
    compute(client, "u", "NODE", str(path), budget_seconds=60)
    assert json.load(open(path))["u/r"]["head"] == "HEAD"


# --- Correction coverage: pagination and cache-safety on a partial repo ---

def test_paginated_history_counts_commits_from_both_pages(tmp_path):
    """A repo whose commit history spans two pages must have BOTH pages counted.

    The reference query only reads history's first page and never follows
    `hasNextPage`; that silently undercounts any repo with more commits by
    this author than fit in one page (the real account's top repo has 187
    commits against a page size of 100). This asserts full pagination.
    """
    path = tmp_path / "loc.json"
    client = ScriptedClient([
        repo_payload([repo("u/r", "HEAD", [commit("c1", 7, 2)],
                            has_next_page=True, end_cursor="cur1")]),
        history_page([commit("c2", 3, 1)]),
    ])
    totals = compute(client, "u", "NODE", str(path), budget_seconds=60)
    assert totals.additions == 10, "second page's commit was not counted"
    assert totals.deletions == 3, "second page's commit was not counted"
    assert client.calls == 2, "expected one repo-list call and one history-page call"
    assert json.load(open(path))["u/r"]["head"] == "HEAD"


def test_budget_expiring_mid_repo_leaves_cache_entry_unchanged(tmp_path):
    """A budget that expires mid-repository must never freeze a partial count.

    Writing the repo's new `head` after only counting its first page would
    make future runs see `head` already matches and skip the repo forever,
    permanently freezing the undercount. The prior entry (head included)
    must be left exactly as it was, and `stale` must come back True.
    """
    path = tmp_path / "loc.json"
    save_cache(str(path), {"u/r": {"head": "OLD", "last_date": "2026-01-01T00:00:00Z",
                                   "additions": 500, "deletions": 100, "oids": []}})
    client = ScriptedClient([
        repo_payload([repo("u/r", "NEW", [commit("c1", 7, 2)],
                            has_next_page=True, end_cursor="cur1")]),
        # No second payload queued: the budget must run out before it would
        # be fetched. If the implementation fetches it anyway, ScriptedClient
        # raises IndexError and this test fails loudly rather than passing.
    ])
    # Clock ticks: [started, pre-repo check (still within budget),
    # pre-next-page check (budget now exhausted)].
    ticks = iter([0, 0, 100])
    totals = compute(client, "u", "NODE", str(path), budget_seconds=10,
                      clock=lambda: next(ticks))

    assert totals.stale is True
    assert totals.additions == 500, "must fall back to the untouched cached figure"
    assert totals.deletions == 100

    cache_after = load_cache(str(path))
    assert cache_after["u/r"]["head"] == "OLD", "partial repo must never update head"
    assert cache_after["u/r"]["additions"] == 500
    assert client.calls == 1, "must not have fetched the second history page"
