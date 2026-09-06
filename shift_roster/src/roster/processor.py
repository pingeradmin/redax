"""Process raw roster records into per-employee and department views."""
from __future__ import annotations

import datetime
from collections import defaultdict
from typing import List, Dict


def group_by_department(records: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for r in records:
        grouped[r.get("department", "Unknown")].append(r)
    return dict(grouped)


def group_by_employee(records: List[dict]) -> Dict[str, dict]:
    return {r["emp_id"]: r for r in records}


def build_employee_message(record: dict) -> str:
    """Personal shift reminder sent to each employee."""
    date_str = _fmt_date(record.get("date"))
    return (
        f"*Shift Reminder* 📋\n"
        f"Hello *{record['emp_name']}*,\n\n"
        f"Your shift for *{date_str}*:\n"
        f"  Shift : *{record['shift_name']}* ({record['shift_code']})\n"
        f"  From  : *{record['shift_start']}*\n"
        f"  To    : *{record['shift_end']}*\n"
        f"  Dept  : {record['department']}\n\n"
        f"Please be on time. Thank you!"
    )


def build_department_summary(dept: str, records: List[dict]) -> str:
    """Summary of all employees in a department for that day."""
    date_str = _fmt_date(records[0]["date"]) if records else ""
    lines = [f"*Shift Roster — {dept}*", f"Date: {date_str}", ""]

    for i, r in enumerate(records, 1):
        lines.append(
            f"{i}. {r['emp_name']}  |  {r['shift_name']} "
            f"({r['shift_start']} – {r['shift_end']})"
        )

    lines.append(f"\nTotal: {len(records)} employee(s)")
    return "\n".join(lines)


def build_full_summary(records: List[dict]) -> str:
    """Full-plant summary for managers."""
    if not records:
        return "No roster records found."

    date_str = _fmt_date(records[0]["date"])
    by_dept = group_by_department(records)

    lines = [
        f"*Daily Shift Roster Report*",
        f"Date: {date_str}",
        f"Total employees: {len(records)}",
        "",
    ]

    for dept, emp_list in sorted(by_dept.items()):
        lines.append(f"*{dept}* ({len(emp_list)})")
        for r in emp_list:
            lines.append(
                f"  • {r['emp_name']}  –  {r['shift_name']} "
                f"({r['shift_start']}–{r['shift_end']})"
            )
        lines.append("")

    return "\n".join(lines)


def _fmt_date(d) -> str:
    if isinstance(d, datetime.date):
        return d.strftime("%d %b %Y (%A)")
    return str(d) if d else ""
