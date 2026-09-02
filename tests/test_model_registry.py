import pytest

from alexios_hermes_control_plane.config import Settings
from alexios_hermes_control_plane.models.registry import ModelRegistry


def test_registry_requires_explicit_credentials() -> None:
    registry = ModelRegistry(Settings(_env_file=None))
    assert registry.configured_roles() == set()
    with pytest.raises(RuntimeError):
        registry.get("judge")


def test_deepseek_configures_only_with_api_key() -> None:
    registry = ModelRegistry(Settings(_env_file=None, deepseek_api_key="secret"))
    assert "implementer" in registry.configured_roles()
