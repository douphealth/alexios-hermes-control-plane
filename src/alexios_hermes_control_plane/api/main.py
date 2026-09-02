import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, status

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.schemas.common import PortfolioRunRequest, RunMode
from alexios_hermes_control_plane.services.ledger import Ledger
from alexios_hermes_control_plane.services.telegram import TelegramClient, parse_portfolio_command
from alexios_hermes_control_plane.services.temporal import WorkflowService

settings = get_settings()
app = FastAPI(title="Alexios Hermes Control Plane", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "environment": settings.app_env,
        "production_writes_enabled": settings.allow_production_writes,
    }


@app.get("/readyz")
async def readyz() -> dict[str, object]:
    ledger = Ledger(settings.database_url)
    try:
        database_ok = await ledger.ping()
    finally:
        await ledger.close()
    return {"status": "ready" if database_ok else "not_ready", "database": database_ok}


@app.post("/v1/runs/portfolio", status_code=status.HTTP_202_ACCEPTED)
async def start_portfolio_run(
    request: PortfolioRunRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, str]:
    try:
        run_id = await WorkflowService(settings).start_portfolio_run(
            request,
            idempotency_key=idempotency_key,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"run_id": run_id, "status": "STARTED"}


@app.get("/v1/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, object]:
    ledger = Ledger(settings.database_url)
    try:
        result = await ledger.get_run(run_id)
    finally:
        await ledger.close()
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return result


@app.post("/telegram/webhook", status_code=status.HTTP_202_ACCEPTED)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, str]:
    try:
        settings.assert_secure_telegram_config()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if settings.telegram_webhook_secret and (
        x_telegram_bot_api_secret_token != settings.telegram_webhook_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")

    update = await request.json()
    update_id = update.get("update_id")
    message = update.get("message") or {}
    user = message.get("from") or {}
    user_id = user.get("id")
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()

    if not isinstance(user_id, int) or not isinstance(chat_id, int):
        return {"status": "IGNORED"}
    if settings.allowed_telegram_users and user_id not in settings.allowed_telegram_users:
        raise HTTPException(status_code=403, detail="Telegram user not allowed")
    if not text:
        return {"status": "IGNORED"}

    objective = parse_portfolio_command(text)
    if objective is not None:
        idempotency_key = f"telegram:{update_id}" if isinstance(update_id, int) else None
        run_id = await WorkflowService(settings).start_portfolio_run(
            PortfolioRunRequest(objective=objective, mode=RunMode.READ_ONLY),
            notification_chat_id=chat_id,
            idempotency_key=idempotency_key,
        )
        await TelegramClient(settings.telegram_bot_token or "").send_message(
            chat_id,
            f"Portfolio run started: {run_id}\nMode: READ_ONLY\nNo production writes are permitted.",
        )
        return {"status": "STARTED", "run_id": run_id}

    return {"status": "IGNORED"}


def run() -> None:
    uvicorn.run(
        "alexios_hermes_control_plane.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
