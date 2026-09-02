import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from alexios_hermes_control_plane.activities.agents import run_judge, run_specialist
from alexios_hermes_control_plane.activities.ledger import (
    ledger_complete_run,
    ledger_create_run,
    ledger_record_agent_result,
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
            run_judge,
            ledger_create_run,
            ledger_record_agent_result,
            ledger_complete_run,
            notify_telegram,
        ],
        max_concurrent_activities=settings.max_concurrent_activities,
    )
    await worker.run()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
