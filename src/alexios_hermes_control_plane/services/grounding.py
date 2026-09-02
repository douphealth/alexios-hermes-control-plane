"""Deterministic evidence eligibility rules applied before the final judge."""

from copy import deepcopy
from typing import Any


def filter_grounded_payloads(
    specialist_payloads: list[dict[str, object]],
    evidence_ids: set[str],
    *,
    partial_confidence_factor: float = 0.6,
) -> list[dict[str, object]]:
    """Return judge-safe copies containing only evidence-eligible findings.

    GROUNDED findings require non-empty cited IDs and every cited ID must exist in the
    run evidence set. PARTIAL findings have the same requirement and receive a deterministic
    confidence penalty. UNGROUNDED and UNVERIFIED findings are never judge-eligible.
    """
    if not 0.0 < partial_confidence_factor <= 1.0:
        raise ValueError("partial_confidence_factor must be within (0, 1]")
    safe: list[dict[str, object]] = []
    for raw_payload in specialist_payloads:
        payload = deepcopy(raw_payload)
        raw_findings = payload.get("findings", [])
        eligible: list[dict[str, Any]] = []
        if isinstance(raw_findings, list):
            for raw_finding in raw_findings:
                if not isinstance(raw_finding, dict):
                    continue
                finding = dict(raw_finding)
                verification = str(finding.get("verification", "UNVERIFIED"))
                cited_raw = finding.get("evidence_ids", [])
                cited = (
                    [str(item) for item in cited_raw]
                    if isinstance(cited_raw, list)
                    else []
                )
                if verification not in {"GROUNDED", "PARTIAL"}:
                    continue
                if not cited or any(item not in evidence_ids for item in cited):
                    continue
                if verification == "PARTIAL":
                    confidence = float(finding.get("confidence", 0.0))
                    finding["confidence"] = round(confidence * partial_confidence_factor, 6)
                eligible.append(finding)
        payload["findings"] = eligible
        payload["evidence_ids"] = sorted(
            {
                evidence_id
                for finding in eligible
                for evidence_id in finding.get("evidence_ids", [])
                if isinstance(evidence_id, str)
            }
        )
        safe.append(payload)
    return safe


def eligible_finding_count(payloads: list[dict[str, object]]) -> int:
    count = 0
    for payload in payloads:
        findings = payload.get("findings", [])
        if isinstance(findings, list):
            count += sum(1 for finding in findings if isinstance(finding, dict))
    return count
