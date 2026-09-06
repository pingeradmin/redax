"""
Pingerbot WhatsApp API client.
API base: https://api1.pingerbot.in
Auth:     instance_id + access_token as query params AND in body.
"""
from __future__ import annotations

import requests

from src.config import config
from src.logger import get_logger

log = get_logger(__name__)

_BASE_URL = config.PINGERBOT_BASE_URL
_SESSION = requests.Session()
_SESSION.headers.update({"Content-Type": "application/json", "Accept": "application/json"})


def _params() -> dict:
    return {
        "instance_id":  config.PINGERBOT_INSTANCE_ID,
        "access_token": config.PINGERBOT_API_TOKEN,
    }


def send_message(phone: str, message: str, media_url: str = "") -> bool:
    """
    Send a WhatsApp direct message to a phone number.

    Args:
        phone:     Recipient number (digits only or with +), e.g. "919876543210"
        message:   Text body
        media_url: Optional media URL for image/file

    Returns:
        True on success.
    """
    if not phone or not message:
        log.warning("send_message: empty phone or message — skipped.")
        return False

    # Pingerbot expects digits only (no leading +)
    clean_phone = phone.lstrip("+")

    payload: dict = {
        "number":       clean_phone,
        "type":         "text",
        "message":      message,
        "instance_id":  config.PINGERBOT_INSTANCE_ID,
        "access_token": config.PINGERBOT_API_TOKEN,
    }
    if media_url:
        payload["media_url"] = media_url
        payload["type"] = "media"

    url = f"{_BASE_URL}/send_message"
    try:
        resp = _SESSION.post(url, json=payload, params=_params(), timeout=15)
        resp.raise_for_status()
        log.info("Sent WA to %s | %s", phone, resp.status_code)
        return True
    except requests.HTTPError as exc:
        log.error("HTTP error sending to %s: %s", phone, exc)
        return False
    except requests.RequestException as exc:
        log.error("Network error sending to %s: %s", phone, exc)
        return False


def send_group_message(group_id: str, message: str, media_url: str = "") -> bool:
    """
    Send a WhatsApp message to a group.

    Args:
        group_id: WhatsApp group JID, e.g. "120363424270484120@g.us"
        message:  Text body
    """
    payload: dict = {
        "group_id":     group_id,
        "type":         "text",
        "message":      message,
        "instance_id":  config.PINGERBOT_INSTANCE_ID,
        "access_token": config.PINGERBOT_API_TOKEN,
    }
    if media_url:
        payload["media_url"] = media_url
        payload["type"] = "media"

    url = f"{_BASE_URL}/send_message"
    try:
        resp = _SESSION.post(url, json=payload, params=_params(), timeout=15)
        resp.raise_for_status()
        log.info("Sent group WA to %s | %s", group_id, resp.status_code)
        return True
    except requests.HTTPError as exc:
        log.error("HTTP error sending to group %s: %s", group_id, exc)
        return False
    except requests.RequestException as exc:
        log.error("Network error sending to group %s: %s", group_id, exc)
        return False


def send_bulk(messages: list[tuple[str, str]]) -> dict:
    """
    Send multiple direct messages.

    Args:
        messages: List of (phone, message_text) tuples.
    """
    sent, failed, failures = 0, 0, []
    for phone, msg in messages:
        if send_message(phone, msg):
            sent += 1
        else:
            failed += 1
            failures.append(phone)
    log.info("Bulk send — sent=%d failed=%d", sent, failed)
    return {"sent": sent, "failed": failed, "failures": failures}


def get_groups() -> list:
    """Fetch all WhatsApp groups for the instance."""
    url = f"{_BASE_URL}/get_groups"
    try:
        resp = _SESSION.get(url, params=_params(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.error("get_groups error: %s", exc)
        return []
