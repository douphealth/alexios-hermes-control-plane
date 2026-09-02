from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Invocation(Generic[T]):
    output: T
    provider_request_id: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ModelAdapter(ABC):
    @abstractmethod
    async def invoke_structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        response_model: type[T],
        prompt_cache_key: str | None = None,
    ) -> Invocation[T]:
        raise NotImplementedError
