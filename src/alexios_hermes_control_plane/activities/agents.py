import json

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


def _context_evidence_ids(context: dict[str, object]) -> set[str]:
    evidence = context.get("evidence", [])
    if not isinstance(evidence, list):
        return set()
    return {
        str(item["evidence_id"])
        for item in evidence
        if isinstance(item, dict) and item.get("evidence_id")
    }


@activity.defn
async def run_judge(
    objective: str,
    specialist_results: list[dict[str, object]],
    context: dict[str, object],
) -> dict[str, object]:
    """Final judge with code-owned evidence validation, scoring and final rank."""
    from alexios_hermes_control_plane.services.scoring import decision_score

    registry = ModelRegistry(get_settings())
    target = registry.get("judge")
    invocation = await target.adapter.invoke_structured(
        model=target.model,
        system=ROLE_PROMPTS["judge"],
        user=(
            f"Objective: {objective}\n"
            f"Context JSON: {json.dumps(context, default=str)}\n"
            f"Specialist results: {json.dumps(specialist_results, default=str)}"
        ),
        response_model=JudgeOutput,
        prompt_cache_key=f"ahcp:judge:{PROMPT_VERSION}",
    )
    judge_output = JudgeOutput.model_validate(invocation.output.model_dump())
    allowed_evidence = _context_evidence_ids(context)
    scored = []
    for intervention in judge_output.interventions:
        if not intervention.evidence_ids:
            continue
        if any(evidence_id not in allowed_evidence for evidence_id in intervention.evidence_ids):
            continue
        score = decision_score(
            impact=intervention.impact,
            confidence=intervention.confidence,
            revenue_alignment=intervention.revenue_alignment,
            effort=intervention.effort,
            reversibility=intervention.reversibility,
            time_to_signal=intervention.time_to_signal,
        )
        scored.append(intervention.model_copy(update={"decision_score": score}))
    ranked = sorted(scored, key=lambda item: (item.decision_score or 0), reverse=True)[:3]
    reranked = [
        item.model_copy(update={"rank": index})
        for index, item in enumerate(ranked, start=1)
    ]
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
