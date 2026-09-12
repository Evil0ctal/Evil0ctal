import pytest
from generator.github import GitHubClient, GitHubError


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload


def test_graphql_returns_data_payload(monkeypatch):
    client = GitHubClient("tok")
    monkeypatch.setattr(
        client._session, "post",
        lambda *a, **k: FakeResponse({"data": {"user": {"login": "x"}}}),
    )
    assert client.graphql("{ viewer { login } }") == {"user": {"login": "x"}}


def test_graphql_raises_on_errors_key(monkeypatch):
    client = GitHubClient("tok")
    monkeypatch.setattr(
        client._session, "post",
        lambda *a, **k: FakeResponse({"errors": [{"message": "Bad credentials"}]}),
    )
    with pytest.raises(GitHubError, match="Bad credentials"):
        client.graphql("{ viewer { login } }")


def test_graphql_raises_on_http_error(monkeypatch):
    client = GitHubClient("tok")
    monkeypatch.setattr(
        client._session, "post", lambda *a, **k: FakeResponse({}, status=502)
    )
    with pytest.raises(GitHubError, match="502"):
        client.graphql("{ viewer { login } }")


def test_missing_token_is_rejected():
    with pytest.raises(GitHubError, match="token"):
        GitHubClient("")
