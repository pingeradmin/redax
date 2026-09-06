"""Read/write roster records in SQLite."""
from __future__ import annotations

import datetime
from typing import List

from src.db.models import RosterEntry, RosterReceiptLog, get_session
from src.logger import get_logger

log = get_logger(__name__)


def save_roster(records: List[dict], raw_message: str, sender: str) -> int:
    """
    Replace all roster entries for the target date and save new ones.
    Returns number of rows saved.
    """
    if not records:
        return 0

    target_date = records[0]["date"]
    session = get_session()
    try:
        # Clear existing entries for that date (daily replace)
        deleted = (
            session.query(RosterEntry)
            .filter(RosterEntry.roster_date == target_date)
            .delete()
        )
        if deleted:
            log.info("Replaced %d existing roster entries for %s", deleted, target_date)

        for rec in records:
            entry = RosterEntry(
                roster_date = rec["date"],
                emp_id      = rec.get("emp_id", ""),
                emp_name    = rec.get("emp_name", ""),
                phone       = rec.get("phone", ""),
                department  = rec.get("department", ""),
                shift_code  = rec.get("shift_code", ""),
                shift_name  = rec.get("shift_name", ""),
                shift_start = rec.get("shift_start", ""),
                shift_end   = rec.get("shift_end", ""),
                source_msg  = raw_message[:500],
            )
            session.add(entry)

        # Audit log
        log_entry = RosterReceiptLog(
            sender      = sender,
            roster_date = target_date,
            raw_message = raw_message,
            parsed_rows = len(records),
            status      = "ok",
        )
        session.add(log_entry)
        session.commit()
        log.info("Saved %d roster entries for %s", len(records), target_date)
        return len(records)
    except Exception as exc:
        session.rollback()
        log.error("Failed to save roster: %s", exc)
        raise
    finally:
        session.close()


def log_receipt_error(sender: str, raw_message: str, error: str):
    session = get_session()
    try:
        entry = RosterReceiptLog(
            sender      = sender,
            raw_message = raw_message,
            parsed_rows = 0,
            status      = f"error: {error[:200]}",
        )
        session.add(entry)
        session.commit()
    finally:
        session.close()


def fetch_roster_from_db(target_date: datetime.date) -> List[dict]:
    """Fetch roster stored in SQLite (replaces etimetracklite connector when roster comes via WA)."""
    session = get_session()
    try:
        rows = (
            session.query(RosterEntry)
            .filter(RosterEntry.roster_date == target_date)
            .order_by(RosterEntry.department, RosterEntry.emp_name)
            .all()
        )
        return [
            {
                "emp_id":      r.emp_id,
                "emp_name":    r.emp_name,
                "phone":       r.phone,
                "department":  r.department or "General",
                "shift_code":  r.shift_code or "",
                "shift_name":  r.shift_name or "",
                "shift_start": r.shift_start or "",
                "shift_end":   r.shift_end or "",
                "date":        r.roster_date,
            }
            for r in rows
        ]
    finally:
        session.close()
