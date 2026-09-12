"""Authenticated GraphQL transport. Fails loudly; never returns partial data."""
import requests

from generator import config


class GitHubError(RuntimeError):
    """Any failure talking to the GitHub API."""


class GitHubClient:
    def __init__(self, token: str, endpoint: str = config.GITHUB_API,
                 timeout: int = config.GITHUB_TIMEOUT_SECONDS):
        if not token:
            raise GitHubError("A GitHub token is required; set ACCESS_TOKEN.")
        self._endpoint = endpoint
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
        })

    def graphql(self, query: str, **variables) -> dict:
        response = self._session.post(
            self._endpoint,
            json={"query": query, "variables": variables},
            timeout=self._timeout,
        )
        if response.status_code != 200:
            raise GitHubError(f"GitHub API returned {response.status_code}: {response.text[:200]}")
        payload = response.json()
        if "errors" in payload:
            messages = "; ".join(e.get("message", "?") for e in payload["errors"])
            raise GitHubError(f"GraphQL error: {messages}")
        if "data" not in payload:
            raise GitHubError("GraphQL response contained no data field.")
        return payload["data"]
