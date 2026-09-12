"""Additions/deletions across owned repos, made cheap by an on-disk cache.

A full walk of every repository's history is far too slow to run daily, so the
cache stores each repo's head OID and running totals. Unchanged repos cost
nothing; changed repos re-read only commits at or after the cached date.

The repository listing query (`REPO_QUERY`) only returns each repo's name and
current head OID — it never embeds commit history, because a single batched
list call shares one set of GraphQL variables across every repo in the page,
and each repo needs its own `since:` boundary (its cached `last_date`, or none
for a repo seen for the first time). So all commit-history fetching, first
page included, goes through `HISTORY_QUERY`, a dedicated per-repository query
that carries that repo's own `since:` and pages via `after:` until GitHub
reports no more pages (`_walk_history`).

A repository's cache entry (in particular its `head`) is written only after
its history has been walked to completion — if the time budget runs out
midway through a repository, that repository's prior cache entry is left
exactly as it was and no further repositories are processed. Recording a new
`head` for a repo we only partially counted would make an undercount
permanent, since every future run would see the head already matches and skip
the repo entirely.

Both pagination cursors (the repo list's and a single repo's history) are
guarded against a cursor that fails to advance: GitHub reporting
`hasNextPage: true` without a usable `endCursor` would otherwise either spin
until the time budget is burned, or (for history, whose cursor argument used
to be typed non-null) crash the whole run via a GraphQL variable-type error,
discarding every repo already completed. Either failure mode is loud
(`LocError`), never a silent under/over-count.
"""
import json
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Callable, Optional

from generator import config


class LocError(RuntimeError):
    """Raised when the GitHub API returns pagination data that cannot be
    trusted — e.g. `hasNextPage: true` paired with a cursor that does not
    advance from the one just used. Walking such a response would either
    infinite-loop or silently refetch the same page forever."""


REPO_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 50, after: $cursor, ownerAffiliations: OWNER, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        defaultBranchRef {
          target {
            ... on Commit { oid }
          }
        }
      }
    }
  }
}
"""

HISTORY_QUERY = """
query($owner: String!, $name: String!, $authorId: ID!, $cursor: String, $pageSize: Int!, $since: GitTimestamp) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: $pageSize, after: $cursor, since: $since, author: {id: $authorId}) {
            pageInfo { hasNextPage endCursor }
            nodes { oid additions deletions committedDate }
          }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class LocTotals:
    additions: int
    deletions: int
    stale: bool


def load_cache(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_cache(path: str, data: dict) -> None:
    """Write the cache atomically so a crash or timeout mid-write can never
    leave a truncated, unparseable `cache/loc.json` behind — that file is a
    committed CI artifact, and `load_cache` would raise on every subsequent
    run until someone deleted it by hand."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=directory or ".", prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, sort_keys=True)
        os.replace(tmp_path, path)
    except BaseException:
        os.remove(tmp_path)
        raise


def _fetch_history_page(client, name: str, user_node_id: str,
                         cursor: Optional[str], since: Optional[str]) -> dict:
    """Fetch one page (the first, if `cursor` is None) of a single
    repository's commit history by this author, from `since` onward."""
    owner, _, repo_name = name.partition("/")
    payload = client.graphql(
        HISTORY_QUERY,
        owner=owner,
        name=repo_name,
        authorId=user_node_id,
        cursor=cursor,
        pageSize=config.LOC_PAGE_SIZE,
        since=since,
    )
    return payload["repository"]["defaultBranchRef"]["target"]["history"]


def _walk_history(client, name: str, user_node_id: str, since: Optional[str],
                   clock_fn: Callable[[], float], started: float,
                   budget_seconds: int):
    """Page through a repository's commit history from `since` to the end.

    Returns `(commits, True)` once the walk reaches the end, or
    `(partial_commits, False)` if the time budget runs out first — the
    caller must discard `partial_commits` and never let a partial walk
    update the cache.

    Raises `LocError` if GitHub reports another page without a cursor that
    actually advances, rather than looping until the budget is exhausted.
    """
    commits: list = []
    cursor = None
    has_next = True
    while has_next:
        if clock_fn() - started >= budget_seconds:
            return commits, False

        history = _fetch_history_page(client, name, user_node_id, cursor, since)
        commits.extend(history["nodes"])

        page_info = history["pageInfo"]
        has_next = page_info.get("hasNextPage", False)
        next_cursor = page_info.get("endCursor")
        if has_next and next_cursor == cursor:
            raise LocError(
                f"{name}: history pagination cursor did not advance "
                f"(stuck at {cursor!r}) while hasNextPage was true; "
                "aborting rather than risk an infinite loop."
            )
        cursor = next_cursor

    return commits, True


def _merge_commits(entry: Optional[dict], commits: list) -> dict:
    """Fold newly-seen commits into a repo's running totals.

    `entry` is the repo's existing cache entry (or None for a fresh repo).
    Commits already recorded under `entry["oids"]` are skipped so a repeated
    `last_date` boundary is never double-counted. Any of those prior boundary
    OIDs that still share the resulting `last_date` are carried forward into
    the new `oids` list — otherwise a boundary commit that this run's payload
    re-returns (because `since` is inclusive of that exact timestamp) but
    that produced no strictly-newer commit would quietly drop out of `oids`,
    and get double-counted the next time it is fetched.
    """
    counted = set(entry.get("oids", [])) if entry else set()
    additions = entry["additions"] if entry else 0
    deletions = entry["deletions"] if entry else 0
    latest_date = entry.get("last_date") if entry else None
    latest_oids = list(counted) if entry else []

    for commit in commits:
        oid = commit["oid"]
        if oid in counted:
            continue
        additions += commit["additions"]
        deletions += commit["deletions"]
        date = commit["committedDate"]
        if latest_date is None or date > latest_date:
            latest_date, latest_oids = date, [oid]
        elif date == latest_date:
            latest_oids.append(oid)

    return {"last_date": latest_date, "additions": additions,
            "deletions": deletions, "oids": latest_oids}


def compute(client, username: str, user_node_id: str, cache_path: str,
            budget_seconds: int = config.LOC_BUDGET_SECONDS,
            clock: Optional[Callable[[], float]] = None) -> LocTotals:
    cache = load_cache(cache_path)
    clock_fn = clock or time.monotonic
    started = clock_fn()
    stale = False

    cursor = None
    while True:
        # Checked at the top of every iteration — not just after the
        # per-repo skip paths below — so the steady-state case (every repo
        # in a page already up to date) still re-checks the budget before
        # firing another repo-list request instead of spinning forever.
        if clock_fn() - started >= budget_seconds:
            stale = True
            break

        data = client.graphql(REPO_QUERY, login=username, cursor=cursor)
        repositories = data["user"]["repositories"]
        budget_exhausted = False

        for node in repositories["nodes"]:
            branch = node.get("defaultBranchRef")
            if not branch or not branch.get("target"):
                continue

            name = node["nameWithOwner"]
            head = branch["target"]["oid"]
            entry = cache.get(name)

            if entry and entry.get("head") == head:
                continue

            if clock_fn() - started >= budget_seconds:
                budget_exhausted = True
                break

            since = entry.get("last_date") if entry else None
            commits, walked_fully = _walk_history(
                client, name, user_node_id, since, clock_fn, started, budget_seconds)
            if not walked_fully:
                budget_exhausted = True
                break  # leave this repo's cache entry untouched

            merged = _merge_commits(entry, commits)
            cache[name] = {"head": head, **merged}
        else:
            page_info = repositories["pageInfo"]
            if page_info["hasNextPage"]:
                next_cursor = page_info["endCursor"]
                if next_cursor == cursor:
                    raise LocError(
                        "repository listing cursor did not advance "
                        f"(stuck at {cursor!r}) while hasNextPage was true; "
                        "aborting rather than risk an infinite loop."
                    )
                cursor = next_cursor
                continue
            break

        # Reaching here means the for-loop above hit `break`, i.e. the
        # budget ran out; stop pulling further pages of repositories too.
        stale = True
        break

    save_cache(cache_path, cache)
    return LocTotals(
        additions=sum(entry["additions"] for entry in cache.values()),
        deletions=sum(entry["deletions"] for entry in cache.values()),
        stale=stale,
    )
