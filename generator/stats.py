"""Profile counters and language mix, derived from GraphQL. No SVG, no files.

Two figures here are *token-scope dependent* and will differ between a
local run and CI:

* `Profile.commits` (`contributionsCollection.totalCommitContributions`)
* the contribution heat map (`generator/calendar.py`, same collection)

Both are computed by GitHub against whatever the presented token can see,
so a broadly-scoped personal token counts private work that CI's narrower
PAT does not. We deliberately do NOT subtract `restrictedContributionsCount`
to force public-only semantics: those semantics are subtle enough that the
fix risks introducing a new wrong number while correcting one, and a wrong
number renders as authoritative. CI's narrower PAT is canonical — after the
first scheduled run, the committed card carries CI's values, and a local
rebuild may briefly show higher ones.

`contributionsCollection` with no `from`/`to` covers the TRAILING TWELVE
MONTHS, not the calendar year; `config.COMMITS_LABEL` says so on the card.
"""
import collections
from dataclasses import dataclass
from datetime import datetime, timezone

from generator import config


class StatsError(RuntimeError):
    """Raised when a payload cannot be summed truthfully — currently, when
    the repository listing has a further page that `first: 100` did not
    return. Star/fork/language totals summed over a truncated node list
    would undercount silently while `totalCount` stayed correct, which is
    exactly the wrong-number-rendered-as-authoritative failure this project
    refuses to ship."""


# `first: 100` is GitHub's per-page maximum. `pageInfo.hasNextPage` is
# requested purely so crossing it fails loudly instead of undercounting.
PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      totalCount
      pageInfo { hasNextPage }
      nodes { stargazerCount forkCount }
    }
    contributionsCollection { totalCommitContributions }
  }
}
"""

LANGUAGE_QUERY = """
query($login: String!) {
  user(login: $login) {
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      pageInfo { hasNextPage }
      nodes { languages(first: 10) { edges { size node { name color } } } }
    }
  }
}
"""


@dataclass(frozen=True)
class Profile:
    created_at: datetime
    followers: int
    repos: int
    stars: int
    forks: int
    commits: int


@dataclass(frozen=True)
class Language:
    name: str
    pct: float
    colour: str


def _require(payload: dict, *path):
    node = payload
    for key in path:
        if not isinstance(node, dict) or key not in node or node[key] is None:
            raise ValueError(f"GraphQL payload missing {'.'.join(path)}")
        node = node[key]
    return node


def _reject_truncated_listing(repos: dict, what: str) -> None:
    """Abort if GitHub says the repository listing has another page.

    Everything summed from `nodes` (stars, forks, the whole language mix)
    is summed over at most the 100 repositories one page returns, while
    `totalCount` stays exact — so crossing 100 would quietly undercount
    with no failure anywhere on the card. Fail loudly instead; paginating
    is a deliberate change to make, not something to guess at silently.
    """
    if (repos.get("pageInfo") or {}).get("hasNextPage"):
        raise StatsError(
            f"more than 100 public source repositories: {what} is summed over "
            "the first page of `repositories(first: 100)` only and would "
            "silently undercount. Paginate the query in generator/stats.py "
            "before trusting this card again."
        )


def fetch_profile(client, username: str) -> Profile:
    data = client.graphql(PROFILE_QUERY, login=username)
    user = _require(data, "user")
    repos = _require(user, "repositories")
    _reject_truncated_listing(repos, "the star and fork total")
    nodes = repos.get("nodes") or []
    return Profile(
        created_at=datetime.strptime(user["createdAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc),
        followers=_require(user, "followers", "totalCount"),
        repos=repos["totalCount"],
        stars=sum(n["stargazerCount"] for n in nodes),
        forks=sum(n["forkCount"] for n in nodes),
        commits=_require(user, "contributionsCollection", "totalCommitContributions"),
    )


def fetch_languages(client, username: str, top: int = config.TOP_LANGUAGES) -> list[Language]:
    """Language mix with every repository weighting the same.

    Summing raw bytes across repositories lets one outlier decide the answer:
    on this account a single reverse-engineering repo carries a ~99 MB vendored
    WebAssembly blob, which is 89% of all bytes and rendered the card as "89.2%
    WebAssembly" for a developer with 22 Python repositories. The bytes were
    real; the conclusion was not.

    So each repository's languages are normalised to sum to 1 first, then
    averaged across repositories. A big repo cannot drown a small one, and a
    vendored binary is worth exactly one repository's vote.
    """
    data = client.graphql(LANGUAGE_QUERY, login=username)
    repos = _require(data, "user", "repositories")
    _reject_truncated_listing(repos, "the language mix")

    shares: collections.Counter = collections.Counter()
    colours: dict[str, str] = {}
    counted_repos = 0
    for repo in repos.get("nodes") or []:
        edges = (repo.get("languages") or {}).get("edges") or []
        repo_total = sum(edge["size"] for edge in edges)
        if not repo_total:
            continue
        counted_repos += 1
        for edge in edges:
            name = edge["node"]["name"]
            shares[name] += edge["size"] / repo_total
            colours[name] = edge["node"].get("color") or config.DIM

    if not counted_repos:
        return []
    return [
        Language(name=name, pct=share * 100 / counted_repos, colour=colours[name])
        for name, share in shares.most_common(top)
    ]


def uptime(created_at: datetime, now: datetime) -> str:
    months = (now.year - created_at.year) * 12 + (now.month - created_at.month)
    if now.day < created_at.day:
        months -= 1
    years, rem = divmod(max(0, months), 12)
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    parts.append(f"{rem} month{'s' if rem != 1 else ''}")
    return ", ".join(parts)
