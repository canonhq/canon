"""Load org-level ticket mapping defaults from a .github repo.

Org-level config is stored in `canon.yaml`
within the org's `.github` repository (the standard GitHub convention for
org-wide config).

The file is loaded asynchronously via the GitHub API, parsed as
CANON.yaml, and the resulting TicketMappingConfig is returned.

Results are cached in-process with a short TTL to avoid redundant API calls
when processing multiple repos for the same org (e.g. cron job).
"""

from __future__ import annotations

import logging
import time

from canon.sync.mapping import TicketMappingConfig

logger = logging.getLogger(__name__)

# Well-known path within the .github repo
ORG_CONFIG_PATH = "canon.yaml"

# In-process TTL cache: {owner: (result, timestamp)}
_cache: dict[str, tuple[TicketMappingConfig | None, float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _cache_get(owner: str) -> tuple[bool, TicketMappingConfig | None]:
    """Check cache for a fresh entry. Returns (hit, value)."""
    entry = _cache.get(owner)
    if entry is None:
        return False, None
    value, ts = entry
    if time.monotonic() - ts > _CACHE_TTL_SECONDS:
        del _cache[owner]
        return False, None
    return True, value


def _cache_set(owner: str, value: TicketMappingConfig | None) -> None:
    _cache[owner] = (value, time.monotonic())


async def load_org_mapping_config(
    client,
    owner: str,
) -> TicketMappingConfig | None:
    """Load org-level TicketMappingConfig from {owner}/.github/canon.yaml.

    Returns None if:
    - The `.github` repo doesn't exist
    - The config file doesn't exist
    - The file fails to parse

    Results are cached for 5 minutes to reduce API calls when processing
    multiple repos for the same org.

    The client must have ``get_file_content(owner, repo, path)`` method
    (GitHubClient protocol).
    """
    hit, cached = _cache_get(owner)
    if hit:
        return cached

    try:
        try:
            content, _sha = await client.get_file_content(owner, ".github", ORG_CONFIG_PATH)
        except Exception:
            content, _sha = await client.get_file_content(owner, ".github", "specwright.yaml")
    except Exception as exc:
        # 404 (repo/file not found) is expected — anything else may indicate
        # auth errors or network issues that ops should investigate.
        exc_str = str(exc)
        if "404" in exc_str or "Not Found" in exc_str:
            logger.debug("No org config found at %s/.github/%s", owner, ORG_CONFIG_PATH)
        else:
            logger.warning(
                "Failed to load org config at %s/.github/%s: %s",
                owner,
                ORG_CONFIG_PATH,
                exc,
            )
        _cache_set(owner, None)
        return None

    if not content or not content.strip():
        _cache_set(owner, None)
        return None

    try:
        from canon.config.parse import parse_canon_yaml

        result = parse_canon_yaml(content)
        if result.config.ticket_mapping:
            logger.info(
                "Loaded org-level ticket mapping from %s/.github/%s",
                owner,
                ORG_CONFIG_PATH,
            )
            _cache_set(owner, result.config.ticket_mapping)
            return result.config.ticket_mapping
        _cache_set(owner, None)
        return None
    except Exception:
        logger.warning(
            "Failed to parse org config at %s/.github/%s",
            owner,
            ORG_CONFIG_PATH,
            exc_info=True,
        )
        _cache_set(owner, None)
        return None
