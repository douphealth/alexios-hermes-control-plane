import httpx


class TelegramClient:
    def __init__(self, token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"

    async def send_message(self, chat_id: int, text: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True},
            )
            response.raise_for_status()


def parse_portfolio_command(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("/portfolio"):
        return None
    objective = stripped.removeprefix("/portfolio").strip()
    return objective or (
        "Identify the three highest-leverage evidence-backed "
        "interventions across the managed portfolio."
    )


def parse_feedback_command(text: str) -> tuple[str, int, str] | None:
    """Parse '/feedback <run-prefix> <rank> <VERDICT> [note]'.

    run-prefix may be shortened: 'portfolio-idem-a1b2' can be referenced as 'a1b2'.
    """
    stripped = text.strip()
    if not stripped.startswith("/feedback"):
        return None
    args = stripped.removeprefix("/feedback").split()
    if len(args) < 3:
        return None
    run_prefix, rank_raw, verdict = args[0], args[1], args[2].upper()
    try:
        rank = int(rank_raw)
    except ValueError:
        return None
    if not 1 <= rank <= 3:
        return None
    if verdict not in {"ADOPTED", "REJECTED", "EXECUTED_VERIFIED", "EXECUTED_NO_SIGNAL", "PARTIAL"}:
        return None
    note = " ".join(args[3:]) or ""
    return run_prefix, rank, f"{verdict} {note}".strip()
