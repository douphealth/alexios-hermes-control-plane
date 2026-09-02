import json

from temporalio import activity

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.models.registry import ModelRegistry
from alexios_hermes_control_plane.prompts import PROMPT_VERSION, ROLE_PROMPTS
from alexios_hermes_control_plane.schemas.common import AgentResult, JudgeOutput, SpecialistOutput


@activity.defn
async def run_specialist(role: str, objective: str, context: dict[str, object]) -> dict[str, object]:
    if role not in {"diagnostician", "strategist", "chief_of_staff"}:
        raise ValueError(f"Unsupported specialist role: {role}")
    registry = ModelRegistry(get_settings())
    target = registry.get(role)
    invocation = await target.adapter.invoke_structured(
        model=target.model,
        system=ROLE_PROMPTS[role],
        user=f"Objective: {objective}\nEvidence/context JSON: {json.dumps(context, default=str)}",
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
async def run_judge(objective: str, specialist_results: list[dict[str, object]]) -> dict[str, object]:
    registry = ModelRegistry(get_settings())
    target = registry.get("judge")
    invocation = await target.adapter.invoke_structured(
        model=target.model,
        system=ROLE_PROMPTS["judge"],
        user=f"Objective: {objective}\nSpecialist results: {json.dumps(specialist_results, default=str)}",
        response_model=JudgeOutput,
        prompt_cache_key=f"ahcp:judge:{PROMPT_VERSION}",
    )
    return {
        "judge_output": invocation.output.model_dump(mode="json"),
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
