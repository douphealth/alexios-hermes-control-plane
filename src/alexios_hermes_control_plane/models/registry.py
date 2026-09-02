from dataclasses import dataclass

from pydantic import BaseModel

from alexios_hermes_control_plane.config import Settings

from .base import ModelAdapter
from .openai_compatible import OpenAICompatibleAdapter
from .openai_responses import OpenAIResponsesAdapter
from .responses_compatible import ResponsesCompatibleAdapter


@dataclass(frozen=True)
class ModelTarget:
    adapter: ModelAdapter[BaseModel]
    model: str


class ModelRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._targets: dict[str, ModelTarget] = {}
        self._configure()

    def _configure(self) -> None:
        s = self.settings
        if s.openai_api_key:
            for role, model, effort in (
                ("chief_of_staff", s.openai_luna_model, s.openai_luna_reasoning),
                ("strategist", s.openai_terra_model, s.openai_terra_reasoning),
                ("judge", s.openai_sol_model, s.openai_sol_reasoning),
            ):
                self._targets[role] = ModelTarget(
                    OpenAIResponsesAdapter(
                        api_key=s.openai_api_key,
                        base_url=s.openai_base_url,
                        reasoning_effort=effort,
                    ),
                    model,
                )

        if s.glm_base_url and s.glm_api_key:
            self._targets["diagnostician"] = ModelTarget(
                OpenAICompatibleAdapter(
                    base_url=s.glm_base_url,
                    api_key=s.glm_api_key,
                    reasoning_effort="low",
                ),
                s.glm_model,
            )
        if s.glm_flash_base_url and s.glm_flash_api_key:
            self._targets["verifier"] = ModelTarget(
                OpenAICompatibleAdapter(
                    base_url=s.glm_flash_base_url,
                    api_key=s.glm_flash_api_key,
                    reasoning_effort="low",
                ),
                s.glm_flash_model,
            )
        if s.deepseek_api_key:
            self._targets["implementer"] = ModelTarget(
                ResponsesCompatibleAdapter(
                    base_url=s.deepseek_base_url,
                    api_key=s.deepseek_api_key,
                    reasoning_effort=s.deepseek_reasoning,
                ),
                s.deepseek_model,
            )

    def get(self, role: str) -> ModelTarget:
        try:
            return self._targets[role]
        except KeyError as exc:
            raise RuntimeError(f"Model role '{role}' is not configured") from exc

    def configured_roles(self) -> set[str]:
        return set(self._targets)
