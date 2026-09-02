import asyncio
from contextlib import suppress
from hashlib import sha256
from uuid import uuid4

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from alexios_hermes_control_plane.config import Settings
from alexios_hermes_control_plane.schemas.common import PortfolioRunRequest, PortfolioWorkflowInput
from alexios_hermes_control_plane.workflows.portfolio import PortfolioOptimizationWorkflow


class TemporalClientManager:
    def __init__(self) -> None:
        self._client: Client | None = None
        self._key: tuple[str, str] | None = None
        self._lock = asyncio.Lock()

    async def get(self, settings: Settings) -> Client:
        key = (settings.temporal_address, settings.temporal_namespace)
        async with self._lock:
            if self._client is None or self._key != key:
                self._client = await Client.connect(
                    settings.temporal_address,
                    namespace=settings.temporal_namespace,
                )
                self._key = key
            return self._client


_client_manager = TemporalClientManager()


class WorkflowService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def start_portfolio_run(
        self,
        request: PortfolioRunRequest,
        *,
        notification_chat_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        if (
            request.mode.value == "PRODUCTION_APPROVED"
            and not self.settings.allow_production_writes
        ):
            raise PermissionError("Production writes are disabled at the control-plane level")
        client = await _client_manager.get(self.settings)
        workflow_id = _workflow_id(idempotency_key)
        payload = PortfolioWorkflowInput(
            request=request,
            notification_chat_id=notification_chat_id,
        )
        with suppress(WorkflowAlreadyStartedError):
            await client.start_workflow(
                PortfolioOptimizationWorkflow.run,
                payload.model_dump(mode="json"),
                id=workflow_id,
                task_queue=self.settings.temporal_task_queue,
            )
        return workflow_id


def _workflow_id(idempotency_key: str | None) -> str:
    if not idempotency_key:
        return f"portfolio-{uuid4().hex[:20]}"
    digest = sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
    return f"portfolio-idem-{digest}"
