"""Orchestration. The only module that sequences network and disk I/O."""
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone

import requests

from generator import avatar, config, loc, stats
from generator import calendar as calendar_mod
from generator.github import GitHubClient, GitHubError
from generator.render import build_svg

log = logging.getLogger("profile")


def _write_atomically(path: str, text: str) -> None:
    """Write `text` to `path` via a same-directory temp file plus
    `os.replace`, mirroring `loc.save_cache` — so an interrupted or failing
    write can never leave a truncated `profile.svg` for CI to commit."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=directory or ".", prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        os.remove(tmp_path)
        raise


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    token = os.environ.get("ACCESS_TOKEN", "")
    if not token:
        log.error("ACCESS_TOKEN is not set. Add it as a repository secret.")
        raise SystemExit(2)

    try:
        client = GitHubClient(token)

        log.info("fetching avatar")
        image = avatar.fetch_avatar(config.USERNAME, config.AVATAR_FETCH_SIZE)
        grid = avatar.build_grid(image, config.AVATAR_COLS)

        log.info("fetching profile and languages")
        profile = stats.fetch_profile(client, config.USERNAME)
        languages = stats.fetch_languages(client, config.USERNAME, config.TOP_LANGUAGES)

        log.info("fetching contribution calendar")
        counts = calendar_mod.fetch_counts(client, config.USERNAME)
        levels = calendar_mod.bucket_levels(counts)
        path = calendar_mod.snake_path(len(levels), len(levels[0]))

        log.info("counting lines changed")
        totals = loc.compute(client, config.USERNAME, config.USER_NODE_ID,
                              config.LOC_CACHE_PATH, config.LOC_BUDGET_SECONDS)
        if totals.stale:
            log.warning("LOC budget exhausted; rendering cached totals")

        svg = build_svg(grid, profile, languages, levels, totals, path,
                         now=datetime.now(timezone.utc))
        _write_atomically(config.OUTPUT_PATH, svg)

    except (GitHubError, requests.exceptions.RequestException, RuntimeError, ValueError) as error:
        log.error("build failed: %s", error)
        raise SystemExit(1)

    log.info("wrote %s (%d bytes)", config.OUTPUT_PATH, len(svg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
