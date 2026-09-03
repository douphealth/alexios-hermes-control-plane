import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from alexios_hermes_control_plane.activities.agents import run_judge, run_specialist, run_verifier
from alexios_hermes_control_plane.activities.context import (
    load_context_config,
    registry_configured_roles,
)
from alexios_hermes_control_plane.activities.evidence import collect_gsc_evidence
from alexios_hermes_control_plane.activities.implementation import run_implementer
from alexios_hermes_control_plane.activities.ledger import (
    ledger_complete_run,
    ledger_create_run,
    ledger_recent_feedback,
    ledger_recent_runs,
    ledger_record_agent_result,
    ledger_record_feedback,
)
from alexios_hermes_control_plane.activities.mutation_guard import (
    mutation_candidate_eligible,
    mutation_target_eligible,
)
from alexios_hermes_control_plane.activities.notifications import notify_telegram
from alexios_hermes_control_plane.activities.outcomes import (
    capture_gsc_baselines,
    list_due_measurements,
    measure_and_record_outcome,
    recent_outcome_memory,
    record_autonomous_mutation,
)
from alexios_hermes_control_plane.activities.technical_evidence import collect_technical_evidence
from alexios_hermes_control_plane.activities.wordpress import (
    wordpress_apply_mutation,
    wordpress_read_target,
    wordpress_rollback_mutation,
    wordpress_validate_mutation,
)
from alexios_hermes_control_plane.activities.wordpress_registry import wordpress_resolve_site
from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.workflows.autonomous import AutonomousGrowthWorkflow
from alexios_hermes_control_plane.workflows.measurement import OutcomeMeasurementWorkflow
from alexios_hermes_control_plane.workflows.portfolio import PortfolioOptimizationWorkflow


async def main() -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[
            PortfolioOptimizationWorkflow,
            AutonomousGrowthWorkflow,
            OutcomeMeasurementWorkflow,
        ],
        activities=[
            run_specialist,
            run_verifier,
            run_judge,
            run_implementer,
            load_context_config,
            registry_configured_roles,
            collect_gsc_evidence,
            collect_technical_evidence,
            capture_gsc_baselines,
            record_autonomous_mutation,
            list_due_measurements,
            measure_and_record_outcome,
            recent_outcome_memory,
            mutation_target_eligible,
            mutation_candidate_eligible,
            ledger_create_run,
            ledger_record_agent_result,
            ledger_complete_run,
            ledger_recent_runs,
            ledger_recent_feedback,
            ledger_record_feedback,
            notify_telegram,
            wordpress_resolve_site,
            wordpress_read_target,
            wordpress_apply_mutation,
            wordpress_validate_mutation,
            wordpress_rollback_mutation,
        ],
        max_concurrent_activities=settings.max_concurrent_activities,
    )
    await worker.run()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
