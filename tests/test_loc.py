import json

from generator.loc import HISTORY_QUERY, REPO_QUERY, LocError, LocTotals, compute, load_cache, save_cache


class ScriptedClient:
    """Returns queued payloads; records every (query, variables) call made.

    Recording the full call (not just a count) lets tests assert on which
    query was used and, critically, which cursor/since value was sent — a
    wrong cursor is exactly the bug that would silently refetch the same
    page forever, and a missing `since` is exactly the bug that would
    silently double-count a repo's whole history on every warm run.
    """

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def graphql(self, query, **variables):
        self.calls.append((query, variables))
        return self.payloads.pop(0)


def repo_list_payload(repos, has_next_page=False, end_cursor=None):
    return {"user": {"repositories": {
        "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
        "nodes": repos,
    }}}


def repo_node(name, head):
    """A repo-list node: identity and head OID only — no embedded history.

    History can't be embedded in the batched list query because each repo
    needs its own `since:` boundary (its cached `last_date`), and a single
    list call shares one set of GraphQL variables across every node in the
    page.
    """
    return {"nameWithOwner": name, "defaultBranchRef": {"target": {"oid": head}}}


def empty_branch_repo_node(name):
    return {"nameWithOwner": name, "defaultBranchRef": None}


def history_payload(commits, has_next_page=False, end_cursor=None):
    """Payload shape for HISTORY_QUERY: one page of one repo's history."""
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
    client = ScriptedClient([repo_list_payload([repo_node("u/r", "SAME")])])
    totals = compute(client, "u", "NODE", str(path), budget_seconds=60)
    assert totals == LocTotals(additions=500, deletions=100, stale=False)
    assert len(client.calls) == 1, "an unchanged head must not trigger a history fetch"


def test_changed_head_adds_new_commits_to_cached_totals(tmp_path):
    path = tmp_path / "loc.json"
    save_cache(str(path), {"u/r": {"head": "OLD", "last_date": "2026-01-01T00:00:00Z",
                                   "additions": 500, "deletions": 100, "oids": []}})
    client = ScriptedClient([
        repo_list_payload([repo_node("u/r", "NEW")]),
        history_payload([commit("c1", 10, 3), commit("c2", 5, 1)]),
    ])
    totals = compute(client, "u", "NODE", str(path), budget_seconds=60)
    assert totals.additions == 515
    assert totals.deletions == 104
    assert totals.stale is False

    history_query, history_vars = client.calls[1]
    assert history_query == HISTORY_QUERY
    assert history_vars["since"] == "2026-01-01T00:00:00Z", \
        "a changed-head repo must re-fetch only since its cached boundary"
    assert history_vars["cursor"] is None


def test_already_counted_oids_are_not_double_counted(tmp_path):
    path = tmp_path / "loc.json"
    save_cache(str(path), {"u/r": {"head": "OLD", "last_date": "2026-09-11T00:00:00Z",
                                   "additions": 500, "deletions": 100, "oids": ["c1"]}})
    client = ScriptedClient([
        repo_list_payload([repo_node("u/r", "NEW")]),
        # A since-filtered server still returns the boundary commit "c1"
        # (since: is inclusive of that exact timestamp) alongside the
        # genuinely new "c2" at the same timestamp.
        history_payload([commit("c1", 10, 3), commit("c2", 5, 1)]),
    ])
    totals = compute(client, "u", "NODE", str(path), budget_seconds=60)
    assert totals.additions == 505, "c1 was already counted"
    assert totals.deletions == 101

    cache_after = load_cache(str(path))
    assert set(cache_after["u/r"]["oids"]) == {"c1", "c2"}, \
        "the prior boundary oid c1 must be carried forward, not dropped, " \
        "or it will be double-counted the next time it is refetched"


def test_fresh_repo_counts_all_commits(tmp_path):
    client = ScriptedClient([
        repo_list_payload([repo_node("u/r", "HEAD")]),
        history_payload([commit("c1", 7, 2)]),
    ])
    totals = compute(client, "u", "NODE", str(tmp_path / "loc.json"), budget_seconds=60)
    assert totals.additions == 7 and totals.deletions == 2

    _, history_vars = client.calls[1]
    assert history_vars["since"] is None, "a cold repo must walk its full history"


def test_empty_default_branch_is_skipped(tmp_path):
    client = ScriptedClient([repo_list_payload([empty_branch_repo_node("u/empty")])])
    totals = compute(client, "u", "NODE", str(tmp_path / "loc.json"), budget_seconds=60)
    assert totals == LocTotals(additions=0, deletions=0, stale=False)


def test_exhausted_budget_marks_result_stale(tmp_path):
    path = tmp_path / "loc.json"
    save_cache(str(path), {"u/r": {"head": "OLD", "last_date": "2026-01-01T00:00:00Z",
                                   "additions": 800, "deletions": 200, "oids": []}})
    # No payloads queued: an already-exhausted budget must be caught at the
    # top of the outer loop, before any API call is made at all.
    client = ScriptedClient([])
    totals = compute(client, "u", "NODE", str(path), budget_seconds=0)
    assert totals.stale is True
    assert totals.additions == 800, "falls back to the cached figure"
    assert len(client.calls) == 0, "an already-exhausted budget must not make any API call"


def test_cache_is_written_back(tmp_path):
    path = tmp_path / "loc.json"
    client = ScriptedClient([
        repo_list_payload([repo_node("u/r", "HEAD")]),
        history_payload([commit("c1", 7, 2)]),
    ])
    compute(client, "u", "NODE", str(path), budget_seconds=60)
    assert json.load(open(path))["u/r"]["head"] == "HEAD"


# --- Correction 1/2 coverage (carried over from the first review round) ---

def test_paginated_history_counts_commits_from_both_pages(tmp_path):
    """A repo whose commit history spans two pages must have BOTH pages
    counted — the real account's top repo has 187 commits against a page
    size of 100."""
    path = tmp_path / "loc.json"
    client = ScriptedClient([
        repo_list_payload([repo_node("u/r", "HEAD")]),
        history_payload([commit("c1", 7, 2)], has_next_page=True, end_cursor="cur1"),
        history_payload([commit("c2", 3, 1)]),
    ])
    totals = compute(client, "u", "NODE", str(path), budget_seconds=60)
    assert totals.additions == 10, "second page's commit was not counted"
    assert totals.deletions == 3, "second page's commit was not counted"
    assert len(client.calls) == 3

    # I6: verify the second history call actually used the cursor GitHub
    # returned, not e.g. an empty one that would silently refetch page 1
    # forever.
    _, second_vars = client.calls[2]
    assert second_vars["cursor"] == "cur1"


def test_budget_expiring_mid_repo_leaves_cache_entry_unchanged(tmp_path):
    """A budget that expires mid-repository must never freeze a partial
    count: the prior entry (head included) must be left exactly as it was,
    and `stale` must come back True."""
    path = tmp_path / "loc.json"
    save_cache(str(path), {"u/r": {"head": "OLD", "last_date": "2026-01-01T00:00:00Z",
                                   "additions": 500, "deletions": 100, "oids": []}})
    client = ScriptedClient([
        repo_list_payload([repo_node("u/r", "NEW")]),
        history_payload([commit("c1", 7, 2)], has_next_page=True, end_cursor="cur1"),
        # No third payload queued: the budget must run out before page 2
        # would be fetched. If it is fetched anyway, ScriptedClient raises
        # IndexError and this test fails loudly instead of passing.
    ])
    # Clock ticks consumed, in order: started, top-of-outer-loop check,
    # per-repo check, pre-page-1-fetch check (all still within budget), then
    # pre-page-2-fetch check (now over budget).
    ticks = iter([0, 0, 0, 0, 100])
    totals = compute(client, "u", "NODE", str(path), budget_seconds=10,
                      clock=lambda: next(ticks))

    assert totals.stale is True
    assert totals.additions == 500, "must fall back to the untouched cached figure"
    assert totals.deletions == 100

    cache_after = load_cache(str(path))
    assert cache_after["u/r"]["head"] == "OLD", "partial repo must never update head"
    assert cache_after["u/r"]["additions"] == 500
    assert len(client.calls) == 2, "must not have fetched the second history page"


# --- Fix round 1 coverage ---

def test_second_run_only_counts_genuinely_new_work(tmp_path):
    """The test that would have caught C1.

    Without a `since:` filter, `_merge_commits` starts accumulating from the
    cached totals while the server keeps returning the *entire* history
    every run, so warm runs double-count. Three consecutive daily runs
    against the same cache, each with exactly one new commit, must total
    60 -> 65 -> 66 (the real work done) — never a compounding figure.

    This reproduces the reviewer's own repro almost exactly: against the
    pre-fix-round code (commit d8d536d), the equivalent scenario produced
    60 -> 65 -> 126 (see task-5-report.md, "Fix round 1", for the standalone
    repro run against that exact commit).
    """
    path = tmp_path / "loc.json"

    # Day 1: cold repo, one commit.
    day1_client = ScriptedClient([
        repo_list_payload([repo_node("u/r", "H1")]),
        history_payload([commit("c1", 60, 0, date="2026-09-01T00:00:00Z")]),
    ])
    totals1 = compute(day1_client, "u", "NODE", str(path), budget_seconds=60)
    assert totals1.additions == 60

    # Day 2: head moved. A correctly since-filtered server returns the
    # boundary commit c1 again (since: is inclusive) plus the one genuinely
    # new c2 -- never the commits further back.
    day2_client = ScriptedClient([
        repo_list_payload([repo_node("u/r", "H2")]),
        history_payload([
            commit("c1", 60, 0, date="2026-09-01T00:00:00Z"),
            commit("c2", 5, 0, date="2026-09-02T00:00:00Z"),
        ]),
    ])
    totals2 = compute(day2_client, "u", "NODE", str(path), budget_seconds=60)
    assert totals2.additions == 65, (
        f"expected the true total 65 after one new 5-line commit, got "
        f"{totals2.additions} -- the accumulator is double-counting history"
    )
    _, day2_history_vars = day2_client.calls[1]
    assert day2_history_vars["since"] == "2026-09-01T00:00:00Z"

    # Day 3: same pattern, one more new commit.
    day3_client = ScriptedClient([
        repo_list_payload([repo_node("u/r", "H3")]),
        history_payload([
            commit("c2", 5, 0, date="2026-09-02T00:00:00Z"),
            commit("c3", 1, 0, date="2026-09-03T00:00:00Z"),
        ]),
    ])
    totals3 = compute(day3_client, "u", "NODE", str(path), budget_seconds=60)
    assert totals3.additions == 66, (
        f"expected the true total 66 after another new 1-line commit, got "
        f"{totals3.additions} -- the accumulator is double-counting history"
    )
    _, day3_history_vars = day3_client.calls[1]
    assert day3_history_vars["since"] == "2026-09-02T00:00:00Z"


def test_repo_list_pagination_uses_returned_cursor(tmp_path):
    """I6/I2: the outer repo-list loop must page using the endCursor GitHub
    actually returns, and must stop once hasNextPage is False."""
    path = tmp_path / "loc.json"
    client = ScriptedClient([
        repo_list_payload([repo_node("u/a", "A")], has_next_page=True, end_cursor="page2"),
        repo_list_payload([repo_node("u/b", "B")]),
    ])
    # Pre-populate both repos as already-current so no history fetch happens;
    # this isolates the repo-list pagination behaviour.
    save_cache(str(path), {
        "u/a": {"head": "A", "last_date": None, "additions": 1, "deletions": 0, "oids": []},
        "u/b": {"head": "B", "last_date": None, "additions": 2, "deletions": 0, "oids": []},
    })
    totals = compute(client, "u", "NODE", str(path), budget_seconds=60)
    assert totals == LocTotals(additions=3, deletions=0, stale=False)
    assert len(client.calls) == 2
    _, second_vars = client.calls[1]
    assert second_vars["cursor"] == "page2"


def test_repo_list_stuck_cursor_raises_loudly(tmp_path):
    """I2: hasNextPage True with a non-advancing endCursor must abort
    loudly rather than spin until the budget burns out."""
    path = tmp_path / "loc.json"
    client = ScriptedClient([
        repo_list_payload([repo_node("u/a", "A")], has_next_page=True, end_cursor=None),
    ])
    save_cache(str(path), {"u/a": {"head": "A", "last_date": None,
                                   "additions": 1, "deletions": 0, "oids": []}})
    try:
        compute(client, "u", "NODE", str(path), budget_seconds=60)
        assert False, "expected LocError for a non-advancing repo-list cursor"
    except LocError:
        pass
    assert len(client.calls) == 1, "must fail on the first stuck response, not retry"


def test_history_stuck_cursor_raises_loudly(tmp_path):
    """I3: a repository's history pagination must abort loudly, not spin,
    if hasNextPage is True but the cursor never advances -- including the
    edge case of hasNextPage: true paired with endCursor: null."""
    path = tmp_path / "loc.json"
    client = ScriptedClient([
        repo_list_payload([repo_node("u/r", "HEAD")]),
        history_payload([commit("c1", 1, 0)], has_next_page=True, end_cursor=None),
    ])
    try:
        compute(client, "u", "NODE", str(path), budget_seconds=60)
        assert False, "expected LocError for a non-advancing history cursor"
    except LocError:
        pass
    assert len(client.calls) == 2, "must fail on the first stuck page, not retry"


def test_history_cursor_variable_is_nullable_for_the_first_page(tmp_path):
    """I3: the first page of a repo's history must be requested with
    cursor=None -- HISTORY_QUERY's $cursor must be a nullable GraphQL type
    ($cursor: String, not $cursor: String!), or a real API would reject a
    null value for a non-null variable."""
    assert "$cursor: String!" not in HISTORY_QUERY
    assert "$cursor: String" in HISTORY_QUERY

    client = ScriptedClient([
        repo_list_payload([repo_node("u/r", "HEAD")]),
        history_payload([commit("c1", 1, 0)]),
    ])
    compute(client, "u", "NODE", str(tmp_path / "loc.json"), budget_seconds=60)
    _, history_vars = client.calls[1]
    assert history_vars["cursor"] is None


def test_save_cache_is_atomic_and_leaves_no_temp_file(tmp_path):
    """I5: save_cache must not truncate the destination in place -- it
    should write to a sibling temp file and atomically replace, so a crash
    mid-write can never leave truncated JSON in the committed cache file."""
    path = tmp_path / "loc.json"
    save_cache(str(path), {"a/b": {"head": "x", "additions": 1, "deletions": 0}})
    save_cache(str(path), {"a/b": {"head": "y", "additions": 2, "deletions": 0}})

    assert load_cache(str(path))["a/b"]["head"] == "y"
    leftovers = [p for p in tmp_path.iterdir() if p.name != "loc.json"]
    assert leftovers == [], f"save_cache left temp files behind: {leftovers}"
