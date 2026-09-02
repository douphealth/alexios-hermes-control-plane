import pytest
from pydantic import BaseModel

from alexios_hermes_control_plane.models.openai_compatible import (
    _message_candidates,
    _parse_structured_message,
)


class Payload(BaseModel):
    status: str


def test_message_candidates_prefers_content_then_reasoning() -> None:
    message = {
        "content": '{"status":"content"}',
        "reasoning_content": '{"status":"reasoning"}',
    }
    assert _message_candidates(message) == [
        '{"status":"content"}',
        '{"status":"reasoning"}',
    ]


def test_reasoning_content_is_accepted_only_when_schema_valid() -> None:
    parsed = _parse_structured_message(
        {"content": "", "reasoning_content": '{"status":"OK"}'},
        Payload,
    )
    assert parsed.status == "OK"


def test_embedded_json_can_be_recovered_from_reasoning_text() -> None:
    parsed = _parse_structured_message(
        {"content": "", "reasoning_content": 'analysis... {"status":"OK"} done'},
        Payload,
    )
    assert parsed.status == "OK"


def test_non_schema_reasoning_is_rejected() -> None:
    with pytest.raises(ValueError, match="none matched the required schema"):
        _parse_structured_message(
            {"content": "", "reasoning_content": '{"wrong":"field"}'},
            Payload,
        )


def test_empty_assistant_message_is_rejected_without_leaking_text() -> None:
    with pytest.raises(ValueError, match="assistant fields"):
        _parse_structured_message({"content": ""}, Payload)
