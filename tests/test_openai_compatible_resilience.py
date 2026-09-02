import pytest
from pydantic import ValidationError

from alexios_hermes_control_plane.models.openai_compatible import _validate_schema_value
from alexios_hermes_control_plane.schemas.common import VerifierOutput


def test_verifier_output_drops_only_harmless_extra_keys() -> None:
    value = {
        "verdicts": [
            {
                "finding_id": "f1",
                "verdict": "GROUNDED",
                "reason": "Supported by evidence.",
                "confidence": 0.99,
                "evidence_ids": ["e1"],
            }
        ],
        "summary": "extra provider commentary",
    }

    output = _validate_schema_value(value, VerifierOutput)

    assert output.model_dump() == {
        "verdicts": [
            {
                "finding_id": "f1",
                "verdict": "GROUNDED",
                "reason": "Supported by evidence.",
            }
        ]
    }


def test_verifier_output_still_rejects_invalid_required_values() -> None:
    value = {
        "verdicts": [
            {
                "finding_id": "f1",
                "verdict": "YES",
                "reason": "Unsupported enum must fail.",
                "confidence": 0.99,
            }
        ]
    }

    with pytest.raises(ValidationError):
        _validate_schema_value(value, VerifierOutput)
