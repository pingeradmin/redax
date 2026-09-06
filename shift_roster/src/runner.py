"""Core job runner: fetch roster → notify employees → send manager report."""
from __future__ import annotations

import datetime
from typing import Optional

from src.config import config
from src.etimetracklite.connector import fetch_roster
from src.logger import get_logger
from src.roster.processor import build_employee_message, build_full_summary
from src.roster.report import whatsapp_report
from src.whatsapp.pingerbot import send_bulk, send_message

log = get_logger(__name__)


def run(target_date: Optional[datetime.date] = None, dry_run: bool = False) -> dict:
    """
    Main job:
    1. Determine target date (today + offset, or explicit date).
    2. Fetch roster from etimetracklite.
    3. Send personal shift reminders to each employee.
    4. Send full summary report to managers.

    Args:
        target_date: Override date; if None uses today + SEND_DAY_OFFSET.
        dry_run:     If True, print messages instead of sending.

    Returns:
        Result dict with sent/failed counts.
    """
    if target_date is None:
        target_date = (
            datetime.date.today()
            + datetime.timedelta(days=config.SEND_DAY_OFFSET)
        )

    log.info("Starting shift roster job for %s (dry_run=%s)", target_date, dry_run)

    records = fetch_roster(target_date)
    if not records:
        log.warning("No roster records found for %s — nothing to send.", target_date)
        return {"sent": 0, "failed": 0, "records": 0}

    # ── 1. Personal reminders ────────────────────────────────────────────
    employee_messages = []
    for rec in records:
        phone = rec.get("phone", "").strip()
        if not phone:
            log.warning("Employee %s has no phone number — skipped.", rec.get("emp_name"))
            continue
        msg = build_employee_message(rec)
        employee_messages.append((phone, msg))

    # ── 2. Manager summary ───────────────────────────────────────────────
    summary = whatsapp_report(records, target_date)
    manager_messages = [(ph, summary) for ph in config.MANAGER_PHONES if ph]

    all_messages = employee_messages + manager_messages
    total = len(all_messages)

    if dry_run:
        log.info("DRY RUN — would send %d messages:", total)
        for phone, msg in all_messages:
            print(f"\n{'─'*50}")
            print(f"TO: {phone}")
            print(msg)
        return {"sent": total, "failed": 0, "records": len(records), "dry_run": True}

    result = send_bulk(all_messages)
    result["records"] = len(records)

    log.info(
        "Job complete for %s — records=%d sent=%d failed=%d",
        target_date, len(records), result["sent"], result["failed"],
    )
    return result
