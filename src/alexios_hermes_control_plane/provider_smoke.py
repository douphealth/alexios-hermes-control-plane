import argparse
import asyncio
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.models.registry import ModelRegistry
from alexios_hermes_control_plane.schemas.common import (
    JudgeOutput,
    SpecialistOutput,
    VerifierOutput,
)
from alexios_hermes_control_plane.schemas.execution import ImplementationPlan

_ROLE_MODELS: dict[str, type[BaseModel]] = {
    "diagnostician": SpecialistOutput,
    "strategist": SpecialistOutput,
    "chief_of_staff": SpecialistOutput,
    "verifier": VerifierOutput,
    "judge": JudgeOutput,
    "implementer": ImplementationPlan,
}


def _roles_for_mode(mode: str) -> tuple[str, ...]:
    base = ("diagnostician", "strategist", "chief_of_staff", "verifier", "judge")
    return base if mode == "READ_ONLY" else (*base, "implementer")


def _smoke_user(role: str) -> str:
    if role in {"diagnostician", "strategist", "chief_of_staff"}:
        return (
            "Provider acceptance test. Return a schema-valid empty specialist result with "
            "status NEEDS_DATA, a short summary, no findings, no evidence_ids, no assumptions, "
            "and error null."
        )
    if role == "verifier":
        return (
            "Provider acceptance test using a realistic verifier payload. Evidence set: "
            '[{"evidence_id":"smoke_e1","source":"smoke","summary":"robots.txt returned HTTP 200",'
            '"site_id":"smoke","kind":"technical_health","payload":{}}]. '
            "Finding to verify: "
            '[{"finding_id":"smoke_f1","category":"technical","title":"robots reachable",'
            '"summary":"robots.txt is reachable","impact":1,"confidence":1.0,'
            '"evidence_ids":["smoke_e1"],"recommended_action":"none",'
            '"verification":"UNVERIFIED"}]. '
            "Return exactly one schema-valid verifier verdict for smoke_f1."
        )
    if role == "judge":
        return "Provider acceptance test. Return a schema-valid judge result with interventions []."
    return (
        "Provider acceptance test. Return a schema-valid implementation plan with a short summary "
        "and mutations []."
    )


async def _check_role(registry: ModelRegistry, role: str) -> dict[str, Any]:
    target = registry.get(role)
    response_model = _ROLE_MODELS[role]
    invocation = await target.adapter.invoke_structured(
        model=target.model,
        system=(
            "This is a connectivity and structured-output acceptance test. "
            "Return only the requested schema-valid JSON."
        ),
        user=_smoke_user(role),
        response_model=response_model,
        prompt_cache_key=f"ahcp:provider-smoke:{role}",
    )
    if role == "verifier":
        output = VerifierOutput.model_validate(invocation.output)
        if len(output.verdicts) != 1 or output.verdicts[0].finding_id != "smoke_f1":
            raise RuntimeError("Verifier acceptance did not return the required realistic verdict")
    return {
        "role": role,
        "model": target.model,
        "latency_ms": invocation.latency_ms,
        "input_tokens": invocation.input_tokens,
        "output_tokens": invocation.output_tokens,
        "status": "PASS",
    }


async def run_checks(mode: str, roles: Sequence[str] | None = None) -> list[dict[str, Any]]:
    normalized_mode = mode.strip().upper()
    if normalized_mode not in {"READ_ONLY", "DRAFT", "STAGING", "PRODUCTION_APPROVED"}:
        raise ValueError(f"Invalid mode: {mode}")
    registry = ModelRegistry(get_settings())
    required = tuple(roles) if roles is not None else _roles_for_mode(normalized_mode)
    configured = registry.configured_roles()
    missing = sorted(set(required) - configured)
    if missing:
        raise RuntimeError(f"Required model roles are not configured: {', '.join(missing)}")

    results: list[dict[str, Any]] = []
    for role in required:
        results.append(await _check_role(registry, role))
    return results


async def _main(mode: str) -> None:
    results = await run_checks(mode)
    for result in results:
        print(
            "PROVIDER_SMOKE "
            f"role={result['role']} model={result['model']} status=PASS "
            f"latency_ms={result['latency_ms']}"
        )
    print(f"PROVIDER_SMOKE_OK roles={len(results)} mode={mode.upper()}")


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="READ_ONLY")
    args = parser.parse_args()
    asyncio.run(_main(args.mode))


if __name__ == "__main__":
    run()
