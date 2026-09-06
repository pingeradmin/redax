"""
Core job runner: fetch roster → notify employees → send manager report.

Roster source priority:
  1. SQLite (populated from WhatsApp or web manual entry)  ← default
  2. etimetracklite SQL/API                               ← ETL_MODE=sql|api in .env
"""
from __future__ import annotations

import datetime
from typing import Optional

from src.config import config
from src.logger import get_logger
from src.roster.processor import build_employee_message
from src.roster.report import whatsapp_report
from src.whatsapp.pingerbot import send_bulk

log = get_logger(__name__)


def _get_records(target_date: datetime.date) -> list:
    """Fetch roster from the configured source."""
    if config.ETL_MODE.lower() in ("sql", "api"):
        from src.etimetracklite.connector import fetch_roster
        return fetch_roster(target_date)
    # Default: SQLite (WhatsApp / web entry)
    from src.db.roster_store import fetch_roster_from_db
    return fetch_roster_from_db(target_date)


def run(target_date: Optional[datetime.date] = None, dry_run: bool = False) -> dict:
    """
    Main job:
    1. Determine target date (today + offset, or explicit).
    2. Fetch roster.
    3. Send personal shift reminders to each employee.
    4. Send full summary to managers.
    """
    if target_date is None:
        target_date = (
            datetime.date.today()
            + datetime.timedelta(days=config.SEND_DAY_OFFSET)
        )

    log.info("Shift roster job for %s (dry_run=%s)", target_date, dry_run)

    records = _get_records(target_date)
    if not records:
        log.warning("No roster records for %s.", target_date)
        return {"sent": 0, "failed": 0, "records": 0}

    # Personal reminders
    employee_messages = []
    for rec in records:
        phone = rec.get("phone", "").strip()
        if not phone:
            log.warning("No phone for %s — skipped.", rec.get("emp_name"))
            continue
        employee_messages.append((phone, build_employee_message(rec)))

    # Manager summary
    summary = whatsapp_report(records, target_date)
    manager_messages = [(ph, summary) for ph in config.MANAGER_PHONES if ph]

    all_messages = employee_messages + manager_messages

    if dry_run:
        log.info("DRY RUN — %d messages:", len(all_messages))
        for phone, msg in all_messages:
            print(f"\n{'─'*50}\nTO: {phone}\n{msg}")
        return {"sent": len(all_messages), "failed": 0, "records": len(records), "dry_run": True}

    result = send_bulk(all_messages)
    result["records"] = len(records)
    log.info("Job done — records=%d sent=%d failed=%d", len(records), result["sent"], result["failed"])
    return result
