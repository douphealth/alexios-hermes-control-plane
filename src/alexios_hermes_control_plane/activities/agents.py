import json
from copy import deepcopy
from typing import Any

from temporalio import activity

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.models.registry import ModelRegistry
from alexios_hermes_control_plane.prompts import PROMPT_VERSION, ROLE_PROMPTS, SPECIALIST_ROLES
from alexios_hermes_control_plane.schemas.common import (
    AgentResult,
    JudgeOutput,
    SpecialistOutput,
    VerifierOutput,
)

_ROLE_ROW_LIMITS = {
    "diagnostician": 10,
    "strategist": 12,
    "verifier": 12,
}
_ROLE_EVIDENCE_KINDS = {
    "diagnostician": {"search_performance_summary", "top_pages"},
    "strategist": {"search_performance_summary", "top_pages", "top_queries"},
    "verifier": {"search_performance_summary", "top_pages", "top_queries"},
}


def _compact_json(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def _evidence_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": item.get("evidence_id"),
        "site_id": item.get("site_id"),
        "kind": item.get("kind"),
        "summary": item.get("summary"),
        "period_start": item.get("period_start"),
        "period_end": item.get("period_end"),
        "payload_hash": item.get("payload_hash"),
    }


def _compact_evidence_item(item: dict[str, Any], row_limit: int) -> dict[str, Any]:
    compact = deepcopy(item)
    payload = compact.get("payload")
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            payload["rows"] = rows[:row_limit]
            payload["rows_truncated"] = max(0, len(rows) - row_limit)
    return compact


def _compact_context_for_role(role: str, context: dict[str, Any]) -> dict[str, Any]:
    """Return a small role-specific model context while preserving evidence provenance."""
    compact: dict[str, Any] = {
        "sites": deepcopy(context.get("sites", [])),
        "mode": context.get("mode", "READ_ONLY"),
        "evidence_note": context.get("evidence_note", ""),
        "operating_rules": deepcopy(context.get("operating_rules", [])),
    }

    raw_evidence = context.get("evidence", [])
    evidence: list[dict[str, Any]] = []
    if isinstance(raw_evidence, list):
        evidence = [item for item in raw_evidence if isinstance(item, dict)]

    if role in {"chief_of_staff", "judge"}:
        compact["evidence"] = [_evidence_summary(item) for item in evidence]
    else:
        allowed_kinds = _ROLE_EVIDENCE_KINDS.get(role)
        if allowed_kinds is not None:
            evidence = [item for item in evidence if str(item.get("kind")) in allowed_kinds]
        row_limit = _ROLE_ROW_LIMITS.get(role, 8)
        compact["evidence"] = [_compact_evidence_item(item, row_limit) for item in evidence]

    if role == "strategist":
        recent_runs = context.get("recent_runs", [])
        compact["recent_runs"] = deepcopy(recent_runs[:3]) if isinstance(recent_runs, list) else []
    elif role == "chief_of_staff":
        recent_runs = context.get("recent_runs", [])
        feedback_memory = context.get("feedback_memory", [])
        compact["recent_runs"] = deepcopy(recent_runs[:5]) if isinstance(recent_runs, list) else []
        compact["feedback_memory"] = (
            deepcopy(feedback_memory[:10]) if isinstance(feedback_memory, list) else []
        )

    return compact


def _reset_specialist_verification(output: SpecialistOutput) -> SpecialistOutput:
    """Ensure specialists cannot self-certify findings before independent verification."""
    sanitized = output.model_copy(deep=True)
    for finding in sanitized.findings:
        finding.verification = "UNVERIFIED"
    return sanitized


def _eligible_specialist_results(
    specialist_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a typed deep copy containing only decision-eligible findings.

    GROUNDED findings pass unchanged. PARTIAL findings pass with a deterministic 50% confidence
    penalty. UNGROUNDED and UNVERIFIED findings are removed before the judge model is called.
    This makes evidence eligibility an application invariant rather than a prompt preference.
    """
    sanitized = deepcopy(specialist_results)
    for payload in sanitized:
        findings = payload.get("findings", [])
        if not isinstance(findings, list):
            payload["findings"] = []
            continue
        eligible: list[dict[str, Any]] = []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            verdict = str(finding.get("verification", "UNVERIFIED"))
            if verdict == "GROUNDED":
                eligible.append(finding)
            elif verdict == "PARTIAL":
                raw_confidence = finding.get("confidence", 0.0)
                confidence = (
                    float(raw_confidence) if isinstance(raw_confidence, (int, float)) else 0.0
                )
                finding["confidence"] = round(confidence * 0.5, 4)
                eligible.append(finding)
        payload["findings"] = eligible
        evidence_ids: list[str] = []
        for finding in eligible:
            raw_ids = finding.get("evidence_ids", [])
            if isinstance(raw_ids, list):
                evidence_ids.extend(str(item) for item in raw_ids)
        payload["evidence_ids"] = sorted(set(evidence_ids))
    return sanitized


@activity.defn
async def run_specialist(
    role: str, objective: str, context: dict[str, Any]
) -> dict[str, Any]:
    if role not in SPECIALIST_ROLES:
        raise ValueError(f"Unsupported specialist role: {role}")
    registry = ModelRegistry(get_settings())
    target = registry.get(role)
    model_context = _compact_context_for_role(role, context)
    invocation = await target.adapter.invoke_structured(
        model=target.model,
        system=ROLE_PROMPTS[role],
        user=(
            f"Objective: {objective}\n"
            f"Context JSON: {_compact_json(model_context)}"
        ),
        response_model=SpecialistOutput,
        prompt_cache_key=f"ahcp:{role}:{PROMPT_VERSION}",
    )
    output = _reset_specialist_verification(invocation.output)
    result = AgentResult(
        **output.model_dump(),
        agent=role,
        model=target.model,
        prompt_version=PROMPT_VERSION,
        provider_request_id=invocation.provider_request_id,
        latency_ms=invocation.latency_ms,
        input_tokens=invocation.input_tokens,
        output_tokens=invocation.output_tokens,
        total_tokens=invocation.total_tokens,
    )
    return result.model_dump(mode="json")


@activity.defn
async def run_verifier(
    objective: str, specialist_results: list[dict[str, Any]], context: dict[str, Any]
) -> dict[str, Any]:
    """Independent grounding check; returns verdicts without mutating findings."""
    registry = ModelRegistry(get_settings())
    target = registry.get("verifier")
    model_context = _compact_context_for_role("verifier", context)
    invocation = await target.adapter.invoke_structured(
        model=target.model,
        system=ROLE_PROMPTS["verifier"],
        user=(
            f"Objective: {objective}\n"
            f"Context JSON: {_compact_json(model_context)}\n"
            f"Specialist results: {_compact_json(specialist_results)}"
        ),
        response_model=VerifierOutput,
        prompt_cache_key=f"ahcp:verifier:{PROMPT_VERSION}",
    )
    output = invocation.output
    telemetry = {
        "agent": "verifier",
        "model": target.model,
        "prompt_version": PROMPT_VERSION,
        "provider_request_id": invocation.provider_request_id,
        "latency_ms": invocation.latency_ms,
        "input_tokens": invocation.input_tokens,
        "output_tokens": invocation.output_tokens,
        "total_tokens": invocation.total_tokens,
    }
    return {
        "verifier_output": output.model_dump(mode="json"),
        "telemetry": telemetry,
    }


@activity.defn
async def run_judge(
    objective: str,
    specialist_results: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Final judge with deterministic evidence eligibility and decision scoring."""
    from alexios_hermes_control_plane.services.scoring import decision_score

    eligible_results = _eligible_specialist_results(specialist_results)
    eligible_count = sum(
        len(findings)
        for item in eligible_results
        if isinstance((findings := item.get("findings", [])), list)
    )
    if eligible_count == 0:
        return {
            "judge_output": JudgeOutput(interventions=[]).model_dump(mode="json"),
            "telemetry": {
                "agent": "judge",
                "model": "not-invoked",
                "prompt_version": PROMPT_VERSION,
                "provider_request_id": None,
                "latency_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
        }

    registry = ModelRegistry(get_settings())
    target = registry.get("judge")
    model_context = _compact_context_for_role("judge", context)
    invocation = await target.adapter.invoke_structured(
        model=target.model,
        system=ROLE_PROMPTS["judge"],
        user=(
            f"Objective: {objective}\n"
            f"Context JSON: {_compact_json(model_context)}\n"
            f"Eligible specialist results: {_compact_json(eligible_results)}"
        ),
        response_model=JudgeOutput,
        prompt_cache_key=f"ahcp:judge:{PROMPT_VERSION}",
    )
    judge_output = JudgeOutput.model_validate(invocation.output.model_dump())
    scored = []
    for intervention in judge_output.interventions:
        score = decision_score(
            impact=intervention.impact,
            confidence=intervention.confidence,
            revenue_alignment=intervention.revenue_alignment,
            effort=intervention.effort,
            reversibility=intervention.reversibility,
            time_to_signal=intervention.time_to_signal,
        )
        scored.append(intervention.model_copy(update={"decision_score": score}))
    ranked = sorted(scored, key=lambda item: (item.decision_score or 0), reverse=True)
    reranked = [item.model_copy(update={"rank": index}) for index, item in enumerate(ranked, 1)]
    return {
        "judge_output": JudgeOutput(interventions=reranked).model_dump(mode="json"),
        "telemetry": {
            "agent": "judge",
            "model": target.model,
            "prompt_version": PROMPT_VERSION,
            "provider_request_id": invocation.provider_request_id,
            "latency_ms": invocation.latency_ms,
            "input_tokens": invocation.input_tokens,
            "output_tokens": invocation.output_tokens,
            "total_tokens": invocation.total_tokens,
        },
    }
