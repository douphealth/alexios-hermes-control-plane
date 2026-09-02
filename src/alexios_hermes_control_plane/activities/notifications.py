from temporalio import activity

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.services.telegram import TelegramClient


@activity.defn
async def notify_telegram(chat_id: int, text: str) -> None:
    token = get_settings().telegram_bot_token
    if not token:
        return
    await TelegramClient(token).send_message(chat_id, text)
