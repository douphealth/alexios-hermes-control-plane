from __future__ import annotations

from typing import Any


_VERDICT_ALIASES = {
    "GROUNDED": "GROUNDED",
    "VERIFIED": "GROUNDED",
    "VALID": "GROUNDED",
    "SUPPORTED": "GROUNDED",
    "PARTIAL": "PARTIAL",
    "PARTIALLY_SUPPORTED": "PARTIAL",
    "PARTIALLY GROUNDED": "PARTIAL",
    "PARTIALLY_GROUNDED": "PARTIAL",
    "UNGROUNDED": "UNGROUNDED",
    "UNSUPPORTED": "UNGROUNDED",
    "INVALID": "UNGROUNDED",
    "NOT_GROUNDED": "UNGROUNDED",
    "NOT GROUNDED": "UNGROUNDED",
}


def normalize_verifier_value(value: object) -> object:
    """Normalize common provider variants into the strict VerifierOutput shape.

    This function never upgrades an unknown verdict to GROUNDED. Unknown or malformed
    values are left invalid so the caller can fail closed.
    """
    if isinstance(value, list):
        raw_verdicts: object = value
    elif isinstance(value, dict):
        if "verdicts" in value:
            raw_verdicts = value["verdicts"]
        else:
            raw_verdicts = None
            for key in ("verifications", "results", "findings", "verification_results"):
                candidate = value.get(key)
                if isinstance(candidate, list):
                    raw_verdicts = candidate
                    break
            if raw_verdicts is None:
                return value
    else:
        return value

    if not isinstance(raw_verdicts, list):
        return value

    normalized: list[dict[str, Any]] = []
    for item in raw_verdicts:
        if not isinstance(item, dict):
            return value
        finding_id = item.get("finding_id") or item.get("findingId") or item.get("id")
        verdict = item.get("verdict") or item.get("verification") or item.get("status")
        reason = item.get("reason") or item.get("rationale") or item.get("explanation")
        if not isinstance(finding_id, str) or not finding_id.strip():
            return value
        if not isinstance(verdict, str):
            return value
        canonical_verdict = _VERDICT_ALIASES.get(verdict.strip().upper())
        if canonical_verdict is None:
            return value
        if not isinstance(reason, str) or not reason.strip():
            reason = "Provider returned no reason; verdict retained only after schema normalization."
        normalized.append(
            {
                "finding_id": finding_id.strip(),
                "verdict": canonical_verdict,
                "reason": reason.strip(),
            }
        )
    return {"verdicts": normalized}
