import json
from time import monotonic
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .base import Invocation, ModelAdapter

T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleAdapter(ModelAdapter):
    """Fallback Chat Completions adapter for OpenAI-compatible providers."""

    def __init__(self, *, base_url: str, api_key: str, timeout: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def invoke_structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        response_model: type[T],
        prompt_cache_key: str | None = None,
    ) -> Invocation[T]:
        schema = response_model.model_json_schema()
        system_with_contract = (
            system
            + "\nReturn JSON only. The JSON must match this schema exactly:\n"
            + json.dumps(schema, separators=(",", ":"))
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_with_contract},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        started = monotonic()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("Provider returned non-string message content")
        try:
            parsed = response_model.model_validate_json(content)
        except ValidationError as exc:
            raise ValueError(f"Provider returned invalid structured output: {exc}") from exc
        usage = data.get("usage") if isinstance(data, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        return Invocation(
            output=parsed,
            provider_request_id=response.headers.get("x-request-id"),
            latency_ms=round((monotonic() - started) * 1000),
            input_tokens=_int_or_none(usage.get("prompt_tokens")),
            output_tokens=_int_or_none(usage.get("completion_tokens")),
            total_tokens=_int_or_none(usage.get("total_tokens")),
        )


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None
