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
        "Identify the three highest-leverage evidence-backed interventions across the managed portfolio."
    )
