import json
from typing import Any

from temporalio import activity

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.models.registry import ModelRegistry
from alexios_hermes_control_plane.schemas.common import Intervention
from alexios_hermes_control_plane.schemas.execution import ImplementationPlan, WordPressSnapshot

_IMPLEMENTER_SYSTEM = """You are the guarded WordPress implementer for an autonomous organic-growth system.
Create the smallest high-confidence change that implements the approved intervention on the exact
existing post snapshot. Preserve user intent, factual claims, author voice, affiliate disclosures,
shortcodes, embeds, media references, and valid HTML. Never invent evidence, statistics, experience,
products, prices, ratings, citations, medical claims, or credentials. Prefer one mutation. Use only
TITLE or CONTENT mutations. Do not change URLs, slugs, status, plugins, themes, canonical tags, or
site-wide settings. Every mutation must cite evidence IDs from the approved intervention. If the
intervention cannot be safely implemented from the supplied snapshot, return zero mutations."""


@activity.defn
async def run_implementer(
    intervention_payload: dict[str, Any], snapshot_payload: dict[str, Any]
) -> dict[str, Any]:
    intervention = Intervention.model_validate(intervention_payload)
    snapshot = WordPressSnapshot.model_validate(snapshot_payload)
    registry = ModelRegistry(get_settings())
    target = registry.get("implementer")
    user = json.dumps(
        {
            "intervention": intervention.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
            "constraints": {
                "site_id": snapshot.site_id,
                "post_id": snapshot.post_id,
                "target_url": intervention.target,
                "allowed_mutation_types": ["TITLE", "CONTENT"],
                "max_mutations": 2,
            },
        },
        separators=(",", ":"),
    )
    invocation = await target.adapter.invoke_structured(
        model=target.model,
        system=_IMPLEMENTER_SYSTEM,
        user=user,
        response_model=ImplementationPlan,
        prompt_cache_key="ahcp:implementer:v1",
    )
    plan = invocation.output
    allowed_evidence = set(intervention.evidence_ids)
    for mutation in plan.mutations:
        if mutation.site_id != snapshot.site_id:
            raise ValueError("Implementer changed the target site")
        if mutation.post_id != snapshot.post_id:
            raise ValueError("Implementer changed the target post")
        if mutation.target_url.rstrip("/") != intervention.target.rstrip("/"):
            raise ValueError("Implementer changed the approved target URL")
        if not set(mutation.evidence_ids).issubset(allowed_evidence):
            raise ValueError("Implementer referenced evidence outside the approved intervention")
    return {
        "plan": plan.model_dump(mode="json"),
        "telemetry": {
            "agent": "implementer",
            "model": target.model,
            "provider_request_id": invocation.provider_request_id,
            "latency_ms": invocation.latency_ms,
            "input_tokens": invocation.input_tokens,
            "output_tokens": invocation.output_tokens,
            "total_tokens": invocation.total_tokens,
        },
    }
