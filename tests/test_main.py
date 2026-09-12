import logging
import os
from datetime import datetime, timezone

import pytest
import requests

from generator import config, main as main_module
from generator.github import GitHubError
from generator.loc import LocTotals
from generator.stats import Language, Profile

PROFILE = Profile(created_at=datetime(2016, 7, 31, tzinfo=timezone.utc),
                  followers=1, repos=2, stars=3, forks=4, commits=5)


@pytest.fixture
def wired(monkeypatch, tmp_path):
    from PIL import Image
    monkeypatch.setenv("ACCESS_TOKEN", "tok")
    monkeypatch.setattr(config, "OUTPUT_PATH", str(tmp_path / "profile.svg"))
    monkeypatch.setattr(config, "LOC_CACHE_PATH", str(tmp_path / "loc.json"))
    monkeypatch.setattr(main_module, "GitHubClient", lambda token: object())
    monkeypatch.setattr(main_module.avatar, "fetch_avatar",
                        lambda user, size=None: Image.new("RGB", (40, 40), (120, 120, 120)))
    monkeypatch.setattr(main_module.stats, "fetch_profile", lambda c, u: PROFILE)
    monkeypatch.setattr(main_module.stats, "fetch_languages",
                        lambda c, u, top=5: [Language("Python", 100.0, "#3572A5")])
    monkeypatch.setattr(main_module.calendar_mod, "fetch_counts",
                        lambda c, u: [[1] * 53 for _ in range(7)])
    monkeypatch.setattr(main_module.loc, "compute",
                        lambda *a, **k: LocTotals(10, 5, False))
    return tmp_path


def test_writes_the_svg_and_returns_zero(wired):
    assert main_module.main([]) == 0
    assert (wired / "profile.svg").read_text().startswith("<svg")


def test_missing_token_fails_loudly(monkeypatch):
    monkeypatch.delenv("ACCESS_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        main_module.main([])


def test_avatar_failure_aborts_the_build(wired, monkeypatch):
    def boom(user, size=None):
        raise RuntimeError("avatar 404")
    monkeypatch.setattr(main_module.avatar, "fetch_avatar", boom)
    with pytest.raises(SystemExit):
        main_module.main([])


def test_graphql_failure_aborts_the_build(wired, monkeypatch):
    def boom(client, username):
        raise GitHubError("Bad credentials")
    monkeypatch.setattr(main_module.stats, "fetch_profile", boom)
    with pytest.raises(SystemExit):
        main_module.main([])


def test_stale_loc_does_not_abort(wired, monkeypatch, caplog):
    monkeypatch.setattr(main_module.loc, "compute",
                        lambda *a, **k: LocTotals(10, 5, True))
    with caplog.at_level(logging.WARNING, logger="profile"):
        assert main_module.main([]) == 0
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "a stale LOC pass must log a WARNING -- this is the only degradation path"
    assert "LOC" in warnings[0].message or "stale" in warnings[0].message.lower()


# --- Fix round 1 coverage ---

def test_network_error_aborts_the_build(wired, monkeypatch):
    """R1: requests.exceptions.ConnectionError/Timeout subclass OSError, not
    RuntimeError/ValueError, so a transient network blip must still be
    caught and turned into a clean SystemExit rather than a raw traceback."""
    def boom(client, username):
        raise requests.exceptions.ConnectionError("connection reset")
    monkeypatch.setattr(main_module.stats, "fetch_profile", boom)
    with pytest.raises(SystemExit):
        main_module.main([])


def test_timeout_aborts_the_build(wired, monkeypatch):
    def boom(client, username):
        raise requests.exceptions.Timeout("timed out")
    monkeypatch.setattr(main_module.stats, "fetch_profile", boom)
    with pytest.raises(SystemExit):
        main_module.main([])


def test_render_failure_aborts_cleanly(wired, monkeypatch):
    """R2: build_svg and the file write now live inside the try block, so a
    failure while rendering must abort via SystemExit, not an unhandled
    crash, and must not leave a partial profile.svg behind."""
    def boom(*a, **k):
        raise ValueError("bad grid")
    monkeypatch.setattr(main_module, "build_svg", boom)
    with pytest.raises(SystemExit):
        main_module.main([])
    assert not (wired / "profile.svg").exists()


def test_write_is_atomic_and_leaves_no_temp_file(wired):
    """R2: the write must go through a same-directory temp file plus
    os.replace, exactly like loc.save_cache -- never a truncated file
    committed by CI."""
    assert main_module.main([]) == 0
    leftovers = [p for p in os.listdir(wired) if p != "profile.svg"]
    assert leftovers == [], f"main() left temp files behind: {leftovers}"
