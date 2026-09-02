from time import monotonic
from typing import TypeVar, cast

from openai import AsyncOpenAI
from pydantic import BaseModel

from .base import Invocation, ModelAdapter

T = TypeVar("T", bound=BaseModel)


class OpenAIResponsesAdapter(ModelAdapter):
    """Native OpenAI Responses API adapter with Pydantic Structured Outputs."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        reasoning_effort: str = "medium",
        timeout: float = 180.0,
    ) -> None:
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.reasoning_effort = reasoning_effort

    async def invoke_structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        response_model: type[T],
        prompt_cache_key: str | None = None,
    ) -> Invocation[T]:
        started = monotonic()
        response = await self.client.responses.parse(
            model=model,
            instructions=system,
            input=user,
            text_format=response_model,
            reasoning={"effort": self.reasoning_effort},
            store=False,
            prompt_cache_key=prompt_cache_key,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("OpenAI Responses API returned no parsed structured output")

        usage = response.usage
        return Invocation(
            output=cast(T, parsed),
            provider_request_id=response.id,
            latency_ms=round((monotonic() - started) * 1000),
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
            total_tokens=getattr(usage, "total_tokens", None) if usage else None,
        )
