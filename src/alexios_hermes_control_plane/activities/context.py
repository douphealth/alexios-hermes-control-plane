"""Context assembly activities.

Workflow code must stay deterministic across replays, so every read of environment
config, model registry state, or the database goes through these activities.
"""

from typing import Any

from temporalio import activity

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.models.registry import ModelRegistry
from alexios_hermes_control_plane.prompts.portfolio_context import (
    OPERATING_RULES,
    load_portfolio_sites,
)


@activity.defn
async def load_context_config(request_sites: list[str]) -> dict[str, Any]:
    """Site registry and operating rules, filtered by the run's requested sites."""
    settings = get_settings()
    sites = load_portfolio_sites(settings.portfolio_sites_json)
    if request_sites:
        requested = {str(s).lower() for s in request_sites}
        filtered = [s for s in sites if str(s.get("site", "")).lower() in requested]
        sites = filtered or [{"site": str(s), "niche": "", "note": ""} for s in request_sites]
    return {
        "sites": sites,
        "operating_rules": list(OPERATING_RULES),
    }


@activity.defn
async def registry_configured_roles() -> list[str]:
    """Which model roles currently have credentials/endpoints configured."""
    registry = ModelRegistry(get_settings())
    return sorted(registry.configured_roles())
