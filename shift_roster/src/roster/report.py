"""Generate text and tabular shift roster reports."""
from __future__ import annotations

import datetime
from typing import List

from tabulate import tabulate

from src.roster.processor import group_by_department


def text_report(records: List[dict], target_date: datetime.date) -> str:
    """Full plain-text/WhatsApp-formatted report grouped by department."""
    if not records:
        return f"No roster data found for {target_date}."

    by_dept = group_by_department(records)
    sections = [
        f"SHIFT ROSTER — {target_date.strftime('%d %b %Y (%A)')}",
        f"Total employees scheduled: {len(records)}",
        "=" * 42,
    ]

    for dept, rows in sorted(by_dept.items()):
        sections.append(f"\n[{dept.upper()}]")
        table = [
            [r["emp_id"], r["emp_name"], r["shift_name"],
             r["shift_start"], r["shift_end"]]
            for r in rows
        ]
        sections.append(
            tabulate(
                table,
                headers=["ID", "Name", "Shift", "In", "Out"],
                tablefmt="simple",
            )
        )
        sections.append(f"  Subtotal: {len(rows)}")

    return "\n".join(sections)


def whatsapp_report(records: List[dict], target_date: datetime.date) -> str:
    """WhatsApp-formatted (markdown) full roster report for managers."""
    if not records:
        return f"No roster data found for {target_date}."

    by_dept = group_by_department(records)
    lines = [
        f"*📋 Shift Roster — {target_date.strftime('%d %b %Y')}*",
        f"Total scheduled: *{len(records)}*",
        "",
    ]

    for dept, rows in sorted(by_dept.items()):
        lines.append(f"*{dept}* ({len(rows)})")
        for r in rows:
            lines.append(
                f"  • {r['emp_name']} — _{r['shift_name']}_ "
                f"{r['shift_start']}–{r['shift_end']}"
            )
        lines.append("")

    return "\n".join(lines)
