import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from alexios_hermes_control_plane.activities.agents import run_judge, run_specialist, run_verifier
from alexios_hermes_control_plane.activities.context import (
    load_context_config,
    registry_configured_roles,
)
from alexios_hermes_control_plane.activities.evidence import collect_gsc_evidence
from alexios_hermes_control_plane.activities.ledger import (
    ledger_complete_run,
    ledger_create_run,
    ledger_recent_feedback,
    ledger_recent_runs,
    ledger_record_agent_result,
    ledger_record_feedback,
)
from alexios_hermes_control_plane.activities.notifications import notify_telegram
from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.workflows.portfolio import PortfolioOptimizationWorkflow


async def main() -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[PortfolioOptimizationWorkflow],
        activities=[
            run_specialist,
            run_verifier,
            run_judge,
            load_context_config,
            registry_configured_roles,
            collect_gsc_evidence,
            ledger_create_run,
            ledger_record_agent_result,
            ledger_complete_run,
            ledger_recent_runs,
            ledger_recent_feedback,
            ledger_record_feedback,
            notify_telegram,
        ],
        max_concurrent_activities=settings.max_concurrent_activities,
    )
    await worker.run()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
