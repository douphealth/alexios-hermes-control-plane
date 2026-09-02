from typing import TypeVar

from pydantic import BaseModel

from .base import Invocation, ModelAdapter

T = TypeVar("T", bound=BaseModel)


class MockModelAdapter[T: BaseModel](ModelAdapter[T]):
    def __init__(self, fixtures: dict[type[BaseModel], BaseModel]) -> None:
        self.fixtures = fixtures

    async def invoke_structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        response_model: type[T],
        prompt_cache_key: str | None = None,
    ) -> Invocation[T]:
        fixture = self.fixtures.get(response_model)
        if fixture is None:
            raise KeyError(f"No mock fixture for {response_model.__name__}")
        return Invocation(output=response_model.model_validate(fixture.model_dump()), latency_ms=1)
