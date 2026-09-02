import json
from copy import deepcopy

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


def _eligible_specialist_results(
    specialist_results: list[dict[str, object]],
) -> list[dict[str, object]]:
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
        eligible: list[dict[str, object]] = []
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
    role: str, objective: str, context: dict[str, object]
) -> dict[str, object]:
    if role not in SPECIALIST_ROLES:
        raise ValueError(f"Unsupported specialist role: {role}")
    registry = ModelRegistry(get_settings())
    target = registry.get(role)
    invocation = await target.adapter.invoke_structured(
        model=target.model,
        system=ROLE_PROMPTS[role],
        user=(
            f"Objective: {objective}\n"
            f"Context JSON: {json.dumps(context, default=str)}"
        ),
        response_model=SpecialistOutput,
        prompt_cache_key=f"ahcp:{role}:{PROMPT_VERSION}",
    )
    output = invocation.output
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
    objective: str, specialist_results: list[dict[str, object]], context: dict[str, object]
) -> dict[str, object]:
    """Independent grounding check; returns verdicts without mutating findings."""
    registry = ModelRegistry(get_settings())
    target = registry.get("verifier")
    invocation = await target.adapter.invoke_structured(
        model=target.model,
        system=ROLE_PROMPTS["verifier"],
        user=(
            f"Objective: {objective}\n"
            f"Context JSON: {json.dumps(context, default=str)}\n"
            f"Specialist results: {json.dumps(specialist_results, default=str)}"
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
    specialist_results: list[dict[str, object]],
    context: dict[str, object],
) -> dict[str, object]:
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
    invocation = await target.adapter.invoke_structured(
        model=target.model,
        system=ROLE_PROMPTS["judge"],
        user=(
            f"Objective: {objective}\n"
            f"Context JSON: {json.dumps(context, default=str)}\n"
            f"Eligible specialist results: {json.dumps(eligible_results, default=str)}"
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
