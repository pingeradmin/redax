"""
Compare shift roster against actual punch records to produce attendance analysis.

Status values:
    PRESENT      Punched IN within grace period of shift start
    LATE         Punched IN after grace period
    EARLY_EXIT   Punched OUT before shift end minus grace period
    ABSENT       No punch record found
    HALF_DAY     Worked less than 50% of shift duration
    OFFICE       Employee not on roster — calculated from raw punch times only
"""
from __future__ import annotations

import datetime
from typing import List, Dict

GRACE_MINUTES = 15   # minutes late still counted as ON TIME


def _to_dt(date: datetime.date, time_str: str) -> datetime.datetime | None:
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


def _calc_worked_from_punches(all_punches: list) -> float:
    """
    Calculate total worked hours from a list of punch datetimes.

    If punches carry IN/OUT labels (dicts with 'time' and 'type'), pair them.
    Otherwise treat as alternating IN/OUT starting from the earliest.
    Returns total hours worked (excluding breaks).
    """
    if not all_punches:
        return 0.0

    # Normalise to sorted list of datetimes
    times = sorted([p if isinstance(p, datetime.datetime) else p for p in all_punches])

    if len(times) == 1:
        return 0.0

    # Pair as IN-OUT, IN-OUT ... (alternating)
    total = 0.0
    i = 0
    while i + 1 < len(times):
        seg = _duration_hours(times[i], times[i + 1])
        total += seg
        i += 2   # skip break: IN(0) OUT(1) | IN(2) OUT(3) ...

    # If odd number of punches: last punch is IN with no matching OUT — ignore it
    return total


def analyse(
    roster: List[dict],
    punch_summary: dict,            # from punch_connector.first_last_punches()
    grace_minutes: int = GRACE_MINUTES,
) -> List[dict]:
    """
    Compare roster vs punches.  Returns list of attendance records.
    """
    grace = datetime.timedelta(minutes=grace_minutes)
    results = []

    for r in roster:
        emp_id = r.get("emp_id", "").strip()
        date   = r["date"]

        scheduled_in  = _to_dt(date, r.get("shift_start", ""))
        scheduled_out = _to_dt(date, r.get("shift_end", ""))

        # Night shift: if end <= start → spans midnight
        if scheduled_in and scheduled_out and scheduled_out <= scheduled_in:
            scheduled_out += datetime.timedelta(days=1)

        shift_hours = _duration_hours(scheduled_in, scheduled_out) if scheduled_in and scheduled_out else 0

        punch = punch_summary.get(emp_id)
        first_in  = punch["first_in"]   if punch else None
        last_out  = punch["last_out"]   if punch else None
        all_p     = punch.get("all_punches", []) if punch else []

        # Multi-punch total hours (pairs of in/out treating alternating punches as breaks)
        if len(all_p) > 2:
            worked_hours = round(_calc_worked_from_punches(all_p), 2)
        else:
            worked_hours = round(_duration_hours(first_in, last_out), 2)

        late_minutes       = 0
        early_exit_minutes = 0

        if not punch or not first_in:
            status = "ABSENT"
        else:
            if scheduled_in and first_in > scheduled_in + grace:
                late_minutes = int((first_in - scheduled_in).total_seconds() / 60)
                status = "LATE"
            else:
                status = "PRESENT"

            if scheduled_out and last_out and last_out < scheduled_out - grace:
                early_exit_minutes = int((scheduled_out - last_out).total_seconds() / 60)
                if status == "PRESENT":
                    status = "EARLY_EXIT"

            if shift_hours > 0 and worked_hours < shift_hours * 0.5:
                status = "HALF_DAY"

        results.append({
            "emp_id":             emp_id,
            "emp_name":           r.get("emp_name", ""),
            "department":         r.get("department", ""),
            "phone":              r.get("phone", ""),
            "shift_name":         r.get("shift_name", ""),
            "shift_start":        r.get("shift_start", ""),
            "shift_end":          r.get("shift_end", ""),
            "first_in":           first_in,
            "last_out":           last_out,
            "first_in_str":       _hhmm(first_in),
            "last_out_str":       _hhmm(last_out),
            "punch_count":        len(all_p),
            "worked_hours":       worked_hours,
            "late_minutes":       late_minutes,
            "early_exit_minutes": early_exit_minutes,
            "status":             status,
            "on_roster":          True,
        })

    results.sort(key=lambda x: (x["department"], x["emp_name"]))
    return results


def analyse_office_employees(
    roster_emp_ids: set,
    punch_summary: dict,
    target_date: datetime.date,
    employee_cache: List[dict],     # [{emp_code, emp_name, department, phone}]
) -> List[dict]:
    """
    For employees NOT in today's roster: compute attendance purely from punches
    (first IN / last OUT), no shift comparison.  Status = OFFICE or ABSENT.
    """
    results = []
    emp_by_code = {e["emp_code"]: e for e in employee_cache}

    for emp_code, punch in punch_summary.items():
        if emp_code in roster_emp_ids:
            continue   # already covered in roster analysis

        emp = emp_by_code.get(emp_code, {})
        emp_name   = punch.get("emp_name") or emp.get("emp_name", f"Emp {emp_code}")
        department = emp.get("department", "")
        phone      = emp.get("phone", "")

        first_in  = punch.get("first_in")
        last_out  = punch.get("last_out")
        all_p     = punch.get("all_punches", [])

        if len(all_p) > 2:
            worked_hours = round(_calc_worked_from_punches(all_p), 2)
        else:
            worked_hours = round(_duration_hours(first_in, last_out), 2)

        status = "OFFICE" if first_in else "ABSENT"

        results.append({
            "emp_id":             emp_code,
            "emp_name":           emp_name,
            "department":         department,
            "phone":              phone,
            "shift_name":         "Office",
            "shift_start":        "",
            "shift_end":          "",
            "first_in":           first_in,
            "last_out":           last_out,
            "first_in_str":       _hhmm(first_in),
            "last_out_str":       _hhmm(last_out),
            "punch_count":        len(all_p),
            "worked_hours":       worked_hours,
            "late_minutes":       0,
            "early_exit_minutes": 0,
            "status":             status,
            "on_roster":          False,
        })

    results.sort(key=lambda x: (x["department"], x["emp_name"]))
    return results


def attendance_whatsapp_report(records: List[dict], target_date: datetime.date) -> str:
    """WhatsApp-formatted attendance summary for managers."""
    total    = len(records)
    present  = sum(1 for r in records if r["status"] in ("PRESENT", "EARLY_EXIT", "OFFICE"))
    late     = sum(1 for r in records if r["status"] == "LATE")
    absent   = sum(1 for r in records if r["status"] == "ABSENT")
    half_day = sum(1 for r in records if r["status"] == "HALF_DAY")

    lines = [
        f"*Attendance Report — {target_date.strftime('%d %b %Y')}*",
        f"Present  : {present}",
        f"Late     : {late}",
        f"Absent   : {absent}",
        f"Half Day : {half_day}",
        f"Total    : {total}",
        "",
    ]

    absent_list = [r for r in records if r["status"] == "ABSENT"]
    if absent_list:
        lines.append("*Absent Employees:*")
        for r in absent_list:
            lines.append(f"  - {r['emp_name']} ({r['department']})")
        lines.append("")

    late_list = [r for r in records if r["status"] == "LATE"]
    if late_list:
        lines.append("*Late Arrivals:*")
        for r in late_list:
            lines.append(
                f"  - {r['emp_name']} — arrived {r['first_in_str']} "
                f"(+{r['late_minutes']} min)"
            )

    return "\n".join(lines)


def attendance_employee_message(record: dict, target_date: datetime.date) -> str:
    """Personal attendance message sent to each employee."""
    status_emoji = {
        "PRESENT":    "✅",
        "LATE":       "⏰",
        "ABSENT":     "❌",
        "EARLY_EXIT": "🚪",
        "HALF_DAY":   "🕐",
        "OFFICE":     "🏢",
    }.get(record["status"], "ℹ️")

    lines = [
        f"*Attendance — {target_date.strftime('%d %b %Y')}*",
        f"Hello *{record['emp_name']}*,",
        "",
        f"Status  : {status_emoji} *{record['status'].replace('_', ' ')}*",
        f"In      : {record['first_in_str']}",
        f"Out     : {record['last_out_str']}",
        f"Worked  : {record['worked_hours']} hrs",
    ]
    if record.get("punch_count", 0) > 2:
        lines.append(f"Punches : {record['punch_count']} (includes breaks)")
    if record.get("late_minutes"):
        lines.append(f"Late by : {record['late_minutes']} minutes")
    if record.get("early_exit_minutes"):
        lines.append(f"Left early by: {record['early_exit_minutes']} minutes")

    return "\n".join(lines)
