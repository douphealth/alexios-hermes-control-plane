import json
from time import monotonic
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from .base import Invocation, ModelAdapter


class OpenAICompatibleAdapter[T: BaseModel](ModelAdapter[T]):
    """Chat Completions adapter with safe handling for reasoning-model response variants."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 180.0,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
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
        schema = response_model.model_json_schema()
        system_with_contract = (
            system
            + "\nReturn JSON only. Do not explain your reasoning. "
            + "The JSON must match this schema exactly:\n"
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
            "max_tokens": self.max_tokens,
        }
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        started = monotonic()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            data, request_id, usage = await self._post(client, headers, payload)
            message = _assistant_message(data)
            try:
                parsed = _parse_structured_message(message, response_model)
            except ValueError:
                repair_instruction = (
                    "Your previous response did not validate. Return ONLY one JSON object "
                    "matching the schema exactly. Do not include prose, markdown, analysis, "
                    "code fences, or extra keys. Original task follows:\n"
                )
                repair_payload = {
                    **payload,
                    "messages": [
                        {"role": "system", "content": system_with_contract},
                        {"role": "user", "content": repair_instruction + user},
                    ],
                }
                data, repair_request_id, repair_usage = await self._post(
                    client, headers, repair_payload
                )
                message = _assistant_message(data)
                parsed = _parse_structured_message(message, response_model)
                request_id = repair_request_id or request_id
                usage = _sum_usage(usage, repair_usage)

        return Invocation(
            output=parsed,
            provider_request_id=request_id,
            latency_ms=round((monotonic() - started) * 1000),
            input_tokens=_int_or_none(usage.get("prompt_tokens")),
            output_tokens=_int_or_none(usage.get("completion_tokens")),
            total_tokens=_int_or_none(usage.get("total_tokens")),
        )

    async def _post(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None, dict[str, Any]]:
        response = await client.post(
            f"{self.base_url}/chat/completions", headers=headers, json=payload
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Provider returned a non-object response")
        raw_usage = data.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        return data, response.headers.get("x-request-id"), usage


def _assistant_message(data: object) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Provider returned a non-object response")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Provider response did not contain choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("Provider returned an invalid choice")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("Provider response did not contain an assistant message")
    return message


def _message_candidates(message: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ("content", "reasoning_content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str):
            value = value.strip()
            if value and value not in candidates:
                candidates.append(value)
    return candidates


def _validate_schema_value[T: BaseModel](value: object, response_model: type[T]) -> T:
    """Return a strict canonical model, tolerating only removable provider extra keys."""
    try:
        return response_model.model_validate(value)
    except ValidationError as strict_error:
        try:
            normalized = response_model.model_validate(value, extra="ignore")
            return response_model.model_validate(normalized.model_dump(mode="python"))
        except ValidationError:
            raise strict_error


def _parse_structured_message[T: BaseModel](
    message: dict[str, Any], response_model: type[T]
) -> T:
    """Accept final/reasoning JSON when it can be canonicalized to the required schema."""
    candidates = _message_candidates(message)
    if not candidates:
        fields = sorted(str(key) for key in message)
        raise ValueError(
            "Provider returned no usable structured text; "
            f"assistant fields={fields}"
        )

    last_error: ValidationError | None = None
    for candidate in candidates:
        try:
            parsed_value = json.loads(candidate)
        except json.JSONDecodeError:
            parsed_value = None
        if parsed_value is not None:
            try:
                return _validate_schema_value(parsed_value, response_model)
            except ValidationError as exc:
                last_error = exc

        decoder = json.JSONDecoder()
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            try:
                return _validate_schema_value(value, response_model)
            except ValidationError as exc:
                last_error = exc

    if last_error is not None:
        raise ValueError(
            "Provider returned structured text, but none matched the required schema"
        ) from last_error
    raise ValueError("Provider returned no schema-valid structured output")


def _sum_usage(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    totals: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        left = first.get(key)
        right = second.get(key)
        if isinstance(left, int) or isinstance(right, int):
            totals[key] = (left if isinstance(left, int) else 0) + (
                right if isinstance(right, int) else 0
            )
    return totals


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None
