import pytest
from pydantic import ValidationError

from alexios_hermes_control_plane.config import Settings
from alexios_hermes_control_plane.schemas.execution import (
    ImplementationPlan,
    MutationType,
    WordPressMutation,
)


def test_production_mode_requires_hard_write_gate() -> None:
    settings = Settings(
        _env_file=None,
        autonomous_growth_mode="PRODUCTION_APPROVED",
        allow_production_writes=False,
        wordpress_sites_json='[{"site_id":"x","base_url":"https://x","username":"u","application_password":"p"}]',
    )
    with pytest.raises(RuntimeError, match="ALLOW_PRODUCTION_WRITES"):
        settings.assert_autonomous_write_safety()


def test_write_mode_requires_wordpress_registry() -> None:
    settings = Settings(
        _env_file=None,
        autonomous_growth_mode="STAGING",
        allow_production_writes=False,
        wordpress_sites_json=None,
    )
    with pytest.raises(RuntimeError, match="WordPress site credentials"):
        settings.assert_autonomous_write_safety()


def test_read_only_mode_does_not_require_wordpress_credentials() -> None:
    settings = Settings(
        _env_file=None,
        autonomous_growth_mode="READ_ONLY",
        wordpress_sites_json=None,
    )
    settings.assert_autonomous_write_safety()


def test_implementation_plan_rejects_duplicate_mutation_ids() -> None:
    base = {
        "mutation_id": "same",
        "site_id": "example.com",
        "target_url": "https://example.com/post/",
        "post_id": 1,
        "mutation_type": MutationType.TITLE,
        "value": "Improved title",
        "reason": "Verified CTR opportunity",
        "evidence_ids": ["ev-1"],
    }
    with pytest.raises(ValidationError, match="mutation_id values must be unique"):
        ImplementationPlan(
            summary="Two duplicate IDs should fail",
            mutations=[WordPressMutation(**base), WordPressMutation(**base)],
        )


def test_implementation_plan_limits_mutations() -> None:
    mutations = [
        WordPressMutation(
            mutation_id=f"m-{index}",
            site_id="example.com",
            target_url="https://example.com/post/",
            post_id=1,
            mutation_type=MutationType.TITLE,
            value=f"Title {index}",
            reason="Verified opportunity",
            evidence_ids=["ev-1"],
        )
        for index in range(4)
    ]
    with pytest.raises(ValidationError):
        ImplementationPlan(summary="Too many mutations", mutations=mutations)
