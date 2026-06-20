"""WhatsApp bridge — send and receive messages via Twilio."""

import logging
import threading
from typing import Callable

from twilio.rest import Client

from .config import settings

logger = logging.getLogger(__name__)


def _client() -> Client:
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def send_message(body: str) -> None:
    """Send a WhatsApp message to the configured recipient.

    Chunks automatically if the body exceeds WhatsApp's 4096-char limit.
    No-ops silently if WhatsApp is not configured.
    """
    if not settings.whatsapp_ready:
        logger.warning("[whatsapp] not configured — message not sent")
        return
    client = _client()
    for chunk in _chunks(body, 4096):
        try:
            msg = client.messages.create(
                from_=settings.twilio_whatsapp_from,
                to=settings.twilio_whatsapp_to,
                body=chunk,
            )
            logger.info("[whatsapp] sent %s", msg.sid)
        except Exception as exc:
            logger.error("[whatsapp] send failed: %s", exc)


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, max(len(text), 1), size)]


def is_authorized(from_: str) -> bool:
    """Only messages from the configured personal number are processed."""
    return bool(settings.twilio_whatsapp_to) and from_ == settings.twilio_whatsapp_to


def reply_async(message: str, handler: Callable[[str], str]) -> None:
    """Run handler(message) in a background thread and send the result via WhatsApp.

    Returns immediately so the Twilio webhook can respond with empty TwiML
    without waiting for the agent to finish.
    """
    def _run() -> None:
        try:
            response = handler(message)
            send_message(response)
        except Exception as exc:
            logger.error("[whatsapp] reply_async failed: %s", exc)
            send_message("⚠️ ALLEN encountered an error processing that message.")

    threading.Thread(target=_run, daemon=True).start()
