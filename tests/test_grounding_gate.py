from alexios_hermes_control_plane.activities.agents import (
    _eligible_specialist_results,
    _reset_specialist_verification,
)
from alexios_hermes_control_plane.schemas.common import SpecialistOutput


def _finding(fid: str, verification: str, confidence: float = 0.8) -> dict[str, object]:
    return {
        "finding_id": fid,
        "category": "seo",
        "title": fid,
        "summary": "summary",
        "impact": 7,
        "confidence": confidence,
        "evidence_ids": ["e1"],
        "recommended_action": "act",
        "verification": verification,
    }


def test_grounding_gate_removes_unverified_and_ungrounded() -> None:
    result = _eligible_specialist_results(
        [
            {
                "agent": "strategist",
                "findings": [
                    _finding("grounded", "GROUNDED"),
                    _finding("partial", "PARTIAL"),
                    _finding("ungrounded", "UNGROUNDED"),
                    _finding("unverified", "UNVERIFIED"),
                ],
            }
        ]
    )
    findings = result[0]["findings"]
    assert isinstance(findings, list)
    assert [item["finding_id"] for item in findings] == ["grounded", "partial"]


def test_partial_finding_confidence_is_discounted() -> None:
    result = _eligible_specialist_results(
        [{"agent": "strategist", "findings": [_finding("partial", "PARTIAL", 0.8)]}]
    )
    findings = result[0]["findings"]
    assert isinstance(findings, list)
    assert findings[0]["confidence"] == 0.4


def test_grounding_gate_does_not_mutate_original_payload() -> None:
    original = [{"agent": "strategist", "findings": [_finding("partial", "PARTIAL", 0.8)]}]
    _eligible_specialist_results(original)
    findings = original[0]["findings"]
    assert isinstance(findings, list)
    assert findings[0]["confidence"] == 0.8


def test_specialist_cannot_self_certify_grounding() -> None:
    output = SpecialistOutput.model_validate(
        {
            "status": "SUCCESS",
            "summary": "candidate",
            "findings": [_finding("self-certified", "GROUNDED")],
            "evidence_ids": ["e1"],
            "assumptions": [],
            "error": None,
        }
    )

    sanitized = _reset_specialist_verification(output)

    assert sanitized.findings[0].verification == "UNVERIFIED"
    assert output.findings[0].verification == "GROUNDED"
