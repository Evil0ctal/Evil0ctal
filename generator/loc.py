"""Additions/deletions across owned repos, made cheap by an on-disk cache.

A full walk of every repository's history is far too slow to run daily, so the
cache stores each repo's head OID and running totals. Unchanged repos cost
nothing; changed repos re-read only commits at or after the cached date.

A repository's commit history is paginated: the initial repo listing query
returns only the first page of a repository's commits, and a repository can
have more commits by this author than fit on one page. `_HISTORY_QUERY` walks
any remaining pages for a single repository until GitHub reports no more
pages. A repository's cache entry (in particular its `head`) is written only
after its history has been walked to completion — if the time budget runs out
midway through a repository, that repository's prior cache entry is left
exactly as it was and no further repositories are processed. Recording a new
`head` for a repo we only partially counted would make the undercount
permanent, since every future run would see the head already matches and skip
the repo entirely.
"""
import json
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

from generator import config

REPO_QUERY = """
query($login: String!, $authorId: ID!, $cursor: String, $pageSize: Int!) {
  user(login: $login) {
    repositories(first: 50, after: $cursor, ownerAffiliations: OWNER, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        defaultBranchRef {
          target {
            ... on Commit {
              oid
              history(first: $pageSize, author: {id: $authorId}) {
                pageInfo { hasNextPage endCursor }
                nodes { oid additions deletions committedDate }
              }
            }
          }
        }
      }
    }
  }
}
"""

HISTORY_QUERY = """
query($owner: String!, $name: String!, $authorId: ID!, $cursor: String!, $pageSize: Int!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: $pageSize, after: $cursor, author: {id: $authorId}) {
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
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)


def _fetch_history_page(client, name: str, user_node_id: str, cursor: str) -> dict:
    """Fetch one further page of a single repository's commit history."""
    owner, _, repo_name = name.partition("/")
    payload = client.graphql(
        HISTORY_QUERY,
        owner=owner,
        name=repo_name,
        authorId=user_node_id,
        cursor=cursor,
        pageSize=config.LOC_PAGE_SIZE,
    )
    return payload["repository"]["defaultBranchRef"]["target"]["history"]


def _merge_commits(entry: Optional[dict], commits: list) -> dict:
    """Fold newly-seen commits into a repo's running totals.

    `entry` is the repo's existing cache entry (or None for a fresh repo).
    Commits already recorded under `entry["oids"]` are skipped so a repeated
    `last_date` boundary is never double-counted.
    """
    counted = set(entry.get("oids", [])) if entry else set()
    additions = entry["additions"] if entry else 0
    deletions = entry["deletions"] if entry else 0
    latest_date = entry.get("last_date") if entry else None
    latest_oids: list = []

    for commit in commits:
        if commit["oid"] in counted:
            continue
        additions += commit["additions"]
        deletions += commit["deletions"]
        date = commit["committedDate"]
        if latest_date is None or date > latest_date:
            latest_date, latest_oids = date, [commit["oid"]]
        elif date == latest_date:
            latest_oids.append(commit["oid"])

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
        data = client.graphql(REPO_QUERY, login=username, authorId=user_node_id,
                               cursor=cursor, pageSize=config.LOC_PAGE_SIZE)
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

            history = branch["target"]["history"]
            commits = list(history["nodes"])
            page_info = history["pageInfo"]

            # Walk any remaining pages of this repo's history before touching
            # the cache. Budget is re-checked before each page fetch so a
            # slow repository can be abandoned mid-walk without ever writing
            # a partial result.
            while page_info.get("hasNextPage"):
                if clock_fn() - started >= budget_seconds:
                    budget_exhausted = True
                    break
                next_history = _fetch_history_page(
                    client, name, user_node_id, page_info["endCursor"])
                commits.extend(next_history["nodes"])
                page_info = next_history["pageInfo"]

            if budget_exhausted:
                break  # leave this repo's cache entry untouched

            merged = _merge_commits(entry, commits)
            cache[name] = {"head": head, **merged}
        else:
            if repositories["pageInfo"]["hasNextPage"]:
                cursor = repositories["pageInfo"]["endCursor"]
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
