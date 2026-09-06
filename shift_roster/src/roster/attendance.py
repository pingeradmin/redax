"""
Compare shift roster against actual punch records to produce attendance analysis.

Status values:
    PRESENT      Punched IN within grace period of shift start
    LATE         Punched IN after grace period
    EARLY_EXIT   Punched OUT before shift end minus grace period
    ABSENT       No punch record found
    HALF_DAY     Worked less than 50% of shift duration
"""
from __future__ import annotations

import datetime
from typing import List

GRACE_MINUTES = 15   # minutes late still counted as ON TIME


def _to_dt(date: datetime.date, time_str: str) -> datetime.datetime | None:
    """Combine a date with a 'HH:MM' string into a datetime."""
    if not time_str:
        return None
    try:
        t = datetime.datetime.strptime(time_str.strip(), "%H:%M").time()
        return datetime.datetime.combine(date, t)
    except ValueError:
        return None


def _hhmm(dt: datetime.datetime | None) -> str:
    return dt.strftime("%H:%M") if dt else "—"


def _duration_hours(start: datetime.datetime, end: datetime.datetime) -> float:
    if start and end and end > start:
        return (end - start).total_seconds() / 3600
    return 0.0


def analyse(
    roster: List[dict],
    punch_summary: dict,            # from punch_connector.first_last_punches()
    grace_minutes: int = GRACE_MINUTES,
) -> List[dict]:
    """
    Compare roster vs punches.

    Returns a list of attendance records:
        {
            emp_id, emp_name, department, phone,
            shift_start, shift_end,           # from roster (str HH:MM)
            first_in, last_out,               # actual punch (datetime | None)
            first_in_str, last_out_str,       # formatted HH:MM
            worked_hours,                     # float
            late_minutes,                     # int (0 if on time)
            early_exit_minutes,               # int (0 if full shift)
            status,                           # PRESENT/LATE/EARLY_EXIT/ABSENT/HALF_DAY
        }
    """
    grace = datetime.timedelta(minutes=grace_minutes)
    results = []

    for r in roster:
        emp_id = r.get("emp_id", "").strip()
        date   = r["date"]

        scheduled_in  = _to_dt(date, r.get("shift_start", ""))
        scheduled_out = _to_dt(date, r.get("shift_end", ""))

        # Handle night shifts: if out < in, shift spans midnight → add 1 day
        if scheduled_in and scheduled_out and scheduled_out <= scheduled_in:
            scheduled_out += datetime.timedelta(days=1)

        shift_hours = _duration_hours(scheduled_in, scheduled_out) if scheduled_in and scheduled_out else 0

        punch = punch_summary.get(emp_id)
        first_in  = punch["first_in"]  if punch else None
        last_out  = punch["last_out"]  if punch else None

        worked_hours       = _duration_hours(first_in, last_out)
        late_minutes       = 0
        early_exit_minutes = 0

        if not punch or not first_in:
            status = "ABSENT"
        else:
            # Late check
            if scheduled_in and first_in > scheduled_in + grace:
                late_minutes = int((first_in - scheduled_in).total_seconds() / 60)
                status = "LATE"
            else:
                status = "PRESENT"

            # Early exit check
            if scheduled_out and last_out and last_out < scheduled_out - grace:
                early_exit_minutes = int((scheduled_out - last_out).total_seconds() / 60)
                if status == "PRESENT":
                    status = "EARLY_EXIT"

            # Half-day check (worked < 50% of shift)
            if shift_hours > 0 and worked_hours < shift_hours * 0.5:
                status = "HALF_DAY"

        results.append({
            "emp_id":             emp_id,
            "emp_name":           r.get("emp_name", ""),
            "department":         r.get("department", ""),
            "phone":              r.get("phone", ""),
            "shift_start":        r.get("shift_start", ""),
            "shift_end":          r.get("shift_end", ""),
            "first_in":           first_in,
            "last_out":           last_out,
            "first_in_str":       _hhmm(first_in),
            "last_out_str":       _hhmm(last_out),
            "worked_hours":       round(worked_hours, 2),
            "late_minutes":       late_minutes,
            "early_exit_minutes": early_exit_minutes,
            "status":             status,
        })

    results.sort(key=lambda x: (x["department"], x["emp_name"]))
    return results


def attendance_whatsapp_report(records: List[dict], target_date: datetime.date) -> str:
    """WhatsApp-formatted attendance summary for managers."""
    total    = len(records)
    present  = sum(1 for r in records if r["status"] in ("PRESENT", "EARLY_EXIT"))
    late     = sum(1 for r in records if r["status"] == "LATE")
    absent   = sum(1 for r in records if r["status"] == "ABSENT")
    half_day = sum(1 for r in records if r["status"] == "HALF_DAY")

    lines = [
        f"*📊 Attendance Report — {target_date.strftime('%d %b %Y')}*",
        f"✅ Present : {present}",
        f"⏰ Late    : {late}",
        f"❌ Absent  : {absent}",
        f"🕐 Half Day: {half_day}",
        f"👥 Total   : {total}",
        "",
    ]

    # Absent list
    absent_list = [r for r in records if r["status"] == "ABSENT"]
    if absent_list:
        lines.append("*❌ Absent Employees:*")
        for r in absent_list:
            lines.append(f"  • {r['emp_name']} ({r['department']})")
        lines.append("")

    # Late list
    late_list = [r for r in records if r["status"] == "LATE"]
    if late_list:
        lines.append("*⏰ Late Arrivals:*")
        for r in late_list:
            lines.append(
                f"  • {r['emp_name']} — arrived {r['first_in_str']} "
                f"(+{r['late_minutes']} min)"
            )
        lines.append("")

    return "\n".join(lines)


def attendance_employee_message(record: dict, target_date: datetime.date) -> str:
    """Personal attendance message sent to each employee."""
    status_emoji = {
        "PRESENT":    "✅",
        "LATE":       "⏰",
        "ABSENT":     "❌",
        "EARLY_EXIT": "🚪",
        "HALF_DAY":   "🕐",
    }.get(record["status"], "ℹ️")

    lines = [
        f"*Attendance Update — {target_date.strftime('%d %b %Y')}*",
        f"Hello *{record['emp_name']}*,",
        "",
        f"Status : {status_emoji} *{record['status'].replace('_', ' ')}*",
        f"In     : {record['first_in_str']}",
        f"Out    : {record['last_out_str']}",
        f"Worked : {record['worked_hours']} hrs",
    ]
    if record["late_minutes"]:
        lines.append(f"Late by: {record['late_minutes']} minutes")
    if record["early_exit_minutes"]:
        lines.append(f"Left early by: {record['early_exit_minutes']} minutes")

    return "\n".join(lines)
