"""Temporal replay tests for the autonomous change-lock gate.

The worker here is an in-process time-skipping server. It does not connect to
the live Temporal namespace, GitHub, or WordPress.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import PatchActivationInput, Replayer, Worker

from alexios_hermes_control_plane.schemas.common import Intervention, PortfolioRunResult, RunMode
from alexios_hermes_control_plane.workflows.autonomous import AutonomousGrowthWorkflow

_PATCH_ID = "axiom-change-lock-v1"
_TARGET = "https://gearuptofit.com/squat/"


@dataclass
class _Gate:
    calls: list[str] = field(default_factory=list)
    lock_allowed: bool = True
    validate_status: str = "VALIDATED"


_GATE = _Gate()


def _analysis() -> dict[str, Any]:
    return PortfolioRunResult(
        run_id="analysis",
        mode=RunMode.READ_ONLY,
        status="DONE",
        interventions=[
            Intervention(
                rank=1,
                title="Improve the title",
                target=_TARGET,
                action="Rewrite the title",
                impact=8,
                confidence=0.9,
                revenue_alignment=7,
                effort=2,
                risk="low",
                reversibility=9,
                time_to_signal=4,
                evidence_ids=["ev-1"],
                expected_signal="CTR",
            )
        ],
        specialist_results=[],
    ).model_dump(mode="json")


def _receipt(status: str) -> dict[str, Any]:
    return {
        "mutation_id": "m1",
        "site_id": "site-1",
        "post_id": 10,
        "post_type": "posts",
        "target_url": _TARGET,
        "status": status,
        "before_sha256": "before",
        "after_sha256": "after",
        "backup_path": "/tmp/ahcp-backup.json",
        "rolled_back": False,
    }


@workflow.defn(name="PortfolioOptimizationWorkflow", sandboxed=False)
class _AnalysisStub:
    @workflow.run
    async def run(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return _analysis()


@activity.defn(name="wordpress_resolve_site")
async def wordpress_resolve_site(_target: str) -> dict[str, Any]:
    _GATE.calls.append("wordpress_resolve_site")
    return {"site_id": "site-1"}


@activity.defn(name="mutation_target_eligible")
async def mutation_target_eligible(
    _site_id: str, _target: str, _cooldown_days: int
) -> dict[str, Any]:
    _GATE.calls.append("mutation_target_eligible")
    return {"eligible": True}


@activity.defn(name="wordpress_read_target")
async def wordpress_read_target(_site_id: str, _target: str) -> dict[str, Any]:
    _GATE.calls.append("wordpress_read_target")
    return {
        "site_id": "site-1",
        "post_id": 10,
        "post_type": "posts",
        "url": _TARGET,
        "slug": "squat",
        "status": "publish",
        "title_raw": "Old title",
        "content_raw": "Body",
    }


@activity.defn(name="run_implementer")
async def run_implementer(
    _intervention: dict[str, Any], _snapshot: dict[str, Any]
) -> dict[str, Any]:
    _GATE.calls.append("run_implementer")
    return {
        "plan": {
            "summary": "Update one title",
            "mutations": [
                {
                    "mutation_id": "m1",
                    "site_id": "site-1",
                    "target_url": _TARGET,
                    "post_id": 10,
                    "mutation_type": "TITLE",
                    "value": "Better squat title",
                    "reason": "Low CTR on the existing title",
                    "evidence_ids": ["ev-1"],
                }
            ],
        },
        "telemetry": {},
    }


@activity.defn(name="mutation_candidate_eligible")
async def mutation_candidate_eligible(
    _mutation: dict[str, Any], _cooldown_days: int
) -> dict[str, Any]:
    _GATE.calls.append("mutation_candidate_eligible")
    return {"eligible": True}


@activity.defn(name="change_lock_acquire")
async def change_lock_acquire(_site_id: str, _task: str, _scope: str) -> dict[str, Any]:
    _GATE.calls.append("change_lock_acquire")
    if _GATE.lock_allowed:
        return {"allowed": True, "seq": 1, "reason": "LOCK_ACQUIRED", "mode": "enforce"}
    return {
        "allowed": False,
        "seq": None,
        "reason": "CHANGE_LOCK_HELD",
        "mode": "enforce",
        "held_by": {"owner": "someone-else"},
    }


@activity.defn(name="capture_gsc_baselines")
async def capture_gsc_baselines(_site_id: str, _target: str) -> dict[str, Any]:
    _GATE.calls.append("capture_gsc_baselines")
    return {}


@activity.defn(name="wordpress_apply_mutation")
async def wordpress_apply_mutation(
    _mutation: dict[str, Any], _snapshot: dict[str, Any], _mode: str
) -> dict[str, Any]:
    _GATE.calls.append("wordpress_apply_mutation")
    return _receipt("APPLIED")


@activity.defn(name="wordpress_validate_mutation")
async def wordpress_validate_mutation(
    _mutation: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    _GATE.calls.append("wordpress_validate_mutation")
    updated = dict(receipt)
    updated["status"] = _GATE.validate_status
    if _GATE.validate_status != "VALIDATED":
        updated["validation_error"] = "title mismatch"
    return updated


@activity.defn(name="record_autonomous_mutation")
async def record_autonomous_mutation(
    _workflow_id: str,
    _mutation: dict[str, Any],
    _receipt: dict[str, Any],
    _baseline: dict[str, Any],
) -> None:
    # The real activity is annotated -> None. Temporal decodes the result with that hint.
    _GATE.calls.append("record_autonomous_mutation")


@activity.defn(name="wordpress_rollback_mutation")
async def wordpress_rollback_mutation(receipt: dict[str, Any]) -> dict[str, Any]:
    _GATE.calls.append("wordpress_rollback_mutation")
    updated = dict(receipt)
    updated["status"] = "ROLLED_BACK"
    updated["rolled_back"] = True
    return updated


@activity.defn(name="change_lock_release")
async def change_lock_release(
    _site_id: str, _task: str, seq: int | None, _evidence: str
) -> dict[str, Any]:
    _GATE.calls.append("change_lock_release")
    return {"released": True, "seq": seq}


_ACTIVITIES = [
    wordpress_resolve_site,
    mutation_target_eligible,
    wordpress_read_target,
    run_implementer,
    mutation_candidate_eligible,
    change_lock_acquire,
    capture_gsc_baselines,
    wordpress_apply_mutation,
    wordpress_validate_mutation,
    record_autonomous_mutation,
    wordpress_rollback_mutation,
    change_lock_release,
]


def _scheduled(history: WorkflowHistory) -> list[str]:
    names: list[str] = []
    for event in history.events:
        if event.HasField("activity_task_scheduled_event_attributes"):
            names.append(event.activity_task_scheduled_event_attributes.activity_type.name)
    return names


def _history_contains(history: WorkflowHistory, text: str) -> bool:
    raw = b"".join(event.SerializeToString() for event in history.events)
    return text.encode() in raw


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping(
        test_server_startup_timeout=timedelta(seconds=90),
    ) as started:
        yield started


async def _run(
    env: WorkflowEnvironment,
    workflow_id: str,
    *,
    lock_allowed: bool = True,
    validate_status: str = "VALIDATED",
    activate_patch: bool = True,
) -> tuple[dict[str, Any], list[str], WorkflowHistory]:
    _GATE.calls.clear()
    _GATE.lock_allowed = lock_allowed
    _GATE.validate_status = validate_status

    def _activate(patch: PatchActivationInput) -> bool:
        return activate_patch or patch.patch_id != _PATCH_ID

    async with Worker(
        env.client,
        task_queue=workflow_id,
        workflows=[AutonomousGrowthWorkflow, _AnalysisStub],
        activities=_ACTIVITIES,
        patch_activation_callback=_activate,
    ):
        handle = await env.client.start_workflow(
            AutonomousGrowthWorkflow.run,
            {
                "objective": "Improve organic traffic",
                "mode": "STAGING",
                "max_interventions": 1,
                "max_mutations_per_site": 1,
            },
            id=workflow_id,
            task_queue=workflow_id,
        )
        result = await asyncio.wait_for(handle.result(), timeout=90)
    history = await handle.fetch_history()
    await Replayer(workflows=[AutonomousGrowthWorkflow]).replay_workflow(history)
    return result, list(_GATE.calls), history


async def test_lock_path_guard_on_acquires_releases_and_replays(
    env: WorkflowEnvironment,
) -> None:
    result, calls, history = await _run(env, "lock-guard-on")
    assert calls == [
        "wordpress_resolve_site",
        "mutation_target_eligible",
        "wordpress_read_target",
        "run_implementer",
        "mutation_candidate_eligible",
        "change_lock_acquire",
        "capture_gsc_baselines",
        "wordpress_apply_mutation",
        "wordpress_validate_mutation",
        "record_autonomous_mutation",
        "change_lock_release",
    ]
    assert _scheduled(history) == calls
    assert _history_contains(history, _PATCH_ID)
    assert result["mutation_receipts"][0]["status"] == "VALIDATED"
    assert result["execution_skips"] == []


async def test_lock_denied_skips_the_write_and_replays(env: WorkflowEnvironment) -> None:
    result, calls, history = await _run(env, "lock-denied", lock_allowed=False)
    assert "change_lock_acquire" in calls
    assert "wordpress_apply_mutation" not in calls
    assert "wordpress_rollback_mutation" not in calls
    assert "change_lock_release" not in calls
    assert _scheduled(history) == calls
    assert _history_contains(history, _PATCH_ID)
    assert result["mutation_receipts"] == []
    assert result["execution_skips"][0]["reason"] == "CHANGE_LOCK_HELD"


async def test_validation_failure_rolls_back_before_release_and_replays(
    env: WorkflowEnvironment,
) -> None:
    result, calls, history = await _run(
        env, "lock-rollback", validate_status="VALIDATION_FAILED"
    )
    assert calls.index("wordpress_rollback_mutation") < calls.index("change_lock_release")
    assert "wordpress_apply_mutation" in calls
    assert _scheduled(history) == calls
    assert result["mutation_receipts"][0]["rolled_back"] is True
    assert result["execution_skips"] == []


async def test_lock_path_guard_off_matches_pre_patch_history_and_replays(
    env: WorkflowEnvironment,
) -> None:
    result, calls, history = await _run(env, "lock-guard-off", activate_patch=False)
    assert "change_lock_acquire" not in calls
    assert "change_lock_release" not in calls
    assert "wordpress_apply_mutation" in calls
    assert "wordpress_rollback_mutation" not in calls
    assert _scheduled(history) == calls
    assert not _history_contains(history, _PATCH_ID)
    assert result["mutation_receipts"][0]["status"] == "VALIDATED"
    assert result["execution_skips"] == []
