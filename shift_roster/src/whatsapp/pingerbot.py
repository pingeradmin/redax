"""Pingerbot WhatsApp API client."""
from __future__ import annotations

import requests

from src.config import config
from src.logger import get_logger

log = get_logger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({
    "Authorization": f"Bearer {config.PINGERBOT_API_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
})


def send_message(phone: str, message: str) -> bool:
    """
    Send a WhatsApp text message via Pingerbot.

    Args:
        phone:   Recipient phone number with country code, e.g. "+919876543210"
        message: Plain-text message body (Pingerbot supports *bold* and _italic_)

    Returns:
        True on success, False on failure.
    """
    if not phone or not message:
        log.warning("send_message called with empty phone or message — skipped.")
        return False

    # Normalise: remove leading + if pingerbot expects plain digits
    # Comment out / adjust based on your pingerbot endpoint requirements.
    clean_phone = phone.lstrip("+")

    payload: dict = {
        "phone":   clean_phone,
        "message": message,
    }

    # Some pingerbot deployments require an instance/session ID
    if config.PINGERBOT_INSTANCE_ID:
        payload["instance_id"] = config.PINGERBOT_INSTANCE_ID

    try:
        resp = _SESSION.post(config.PINGERBOT_API_URL, json=payload, timeout=15)
        resp.raise_for_status()
        log.info("Sent WA message to %s | status %s", phone, resp.status_code)
        return True
    except requests.HTTPError as exc:
        log.error("HTTP error sending to %s: %s", phone, exc)
        return False
    except requests.RequestException as exc:
        log.error("Network error sending to %s: %s", phone, exc)
        return False


def send_bulk(messages: list[tuple[str, str]]) -> dict:
    """
    Send multiple messages.

    Args:
        messages: List of (phone, message) tuples.

    Returns:
        {"sent": int, "failed": int, "failures": [phone, ...]}
    """
    sent = 0
    failed = 0
    failures = []

    for phone, msg in messages:
        if send_message(phone, msg):
            sent += 1
        else:
            failed += 1
            failures.append(phone)

    log.info("Bulk send complete — sent=%d failed=%d", sent, failed)
    return {"sent": sent, "failed": failed, "failures": failures}
