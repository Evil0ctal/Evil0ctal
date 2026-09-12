"""Profile counters and language mix, derived from GraphQL. No SVG, no files."""
import collections
from dataclasses import dataclass
from datetime import datetime, timezone

from generator import config

PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
      totalCount
      nodes { stargazerCount forkCount }
    }
    contributionsCollection { totalCommitContributions }
  }
}
"""

LANGUAGE_QUERY = """
query($login: String!) {
  user(login: $login) {
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
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


def fetch_profile(client, username: str) -> Profile:
    data = client.graphql(PROFILE_QUERY, login=username)
    user = _require(data, "user")
    repos = _require(user, "repositories")
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
    data = client.graphql(LANGUAGE_QUERY, login=username)
    totals: collections.Counter = collections.Counter()
    colours: dict[str, str] = {}
    for repo in _require(data, "user", "repositories").get("nodes") or []:
        for edge in (repo.get("languages") or {}).get("edges") or []:
            name = edge["node"]["name"]
            totals[name] += edge["size"]
            colours[name] = edge["node"].get("color") or config.DIM
    grand_total = sum(totals.values())
    if not grand_total:
        return []
    return [
        Language(name=name, pct=size * 100 / grand_total, colour=colours[name])
        for name, size in totals.most_common(top)
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
