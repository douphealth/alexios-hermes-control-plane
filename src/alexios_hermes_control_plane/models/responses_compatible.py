from time import monotonic
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from .base import Invocation, ModelAdapter

T = TypeVar("T", bound=BaseModel)


class ResponsesCompatibleAdapter(ModelAdapter):
    """OpenAI Responses-compatible adapter using JSON Schema structured output."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        reasoning_effort: str | None = None,
        timeout: float = 180.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
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
        payload: dict[str, Any] = {
            "model": model,
            "instructions": system,
            "input": user,
            "text": {"format": {"type": "json_schema", "name": response_model.__name__[:64], "schema": schema}},
            "store": False,
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        started = monotonic()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/responses", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        text = _extract_output_text(data)
        parsed = response_model.model_validate_json(text)
        usage = data.get("usage") if isinstance(data, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        return Invocation(
            output=parsed,
            provider_request_id=str(data.get("id")) if data.get("id") else None,
            latency_ms=round((monotonic() - started) * 1000),
            input_tokens=_int_or_none(usage.get("input_tokens")),
            output_tokens=_int_or_none(usage.get("output_tokens")),
            total_tokens=_int_or_none(usage.get("total_tokens")),
        )


def _extract_output_text(data: dict[str, Any]) -> str:
    output = data.get("output")
    if not isinstance(output, list):
        raise ValueError("Responses-compatible provider returned no output list")
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str) and text:
                    return text
    raise ValueError("Responses-compatible provider returned no output_text content")


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None
