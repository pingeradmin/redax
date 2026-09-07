"""
PDF report generator using reportlab.

Exports:
    daily_pdf(records, target_date, company_name) -> bytes
    monthly_pdf(records, year, month, company_name) -> bytes
    employee_pdf(records, emp_name, company_name) -> bytes
"""
from __future__ import annotations

import datetime
import io
from typing import List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT


# ── Helpers ───────────────────────────────────────────────────────────────────

HEADER_COLOR = colors.HexColor("#1a3c5e")
ALT_ROW_COLOR = colors.HexColor("#edf2f7")
STATUS_COLORS = {
    "PRESENT":    colors.HexColor("#c6f6d5"),
    "LATE":       colors.HexColor("#fefcbf"),
    "ABSENT":     colors.HexColor("#fed7d7"),
    "EARLY_EXIT": colors.HexColor("#feebc8"),
    "HALF_DAY":   colors.HexColor("#e9d8fd"),
    "OFFICE":     colors.HexColor("#bee3f8"),
}


def _styles():
    s = getSampleStyleSheet()
    title = ParagraphStyle(
        "ReportTitle",
        parent=s["Title"],
        fontSize=16, textColor=HEADER_COLOR, alignment=TA_CENTER,
        spaceAfter=4,
    )
    subtitle = ParagraphStyle(
        "ReportSubtitle",
        parent=s["Normal"],
        fontSize=10, alignment=TA_CENTER, textColor=colors.grey,
        spaceAfter=12,
    )
    label = ParagraphStyle(
        "Label",
        parent=s["Normal"],
        fontSize=9, textColor=colors.grey,
    )
    return title, subtitle, label, s


def _header_table_style(ncols: int) -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_COLOR),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 9),
        ("ALIGN",      (0, 0), (-1, 0), "CENTER"),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("FONTSIZE",   (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW_COLOR]),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
    ])


def _add_status_row_colors(style: TableStyle, data_rows: list):
    for i, row in enumerate(data_rows, start=1):
        status = row[-1] if row else ""
        bg = STATUS_COLORS.get(str(status), None)
        if bg:
            style.add("BACKGROUND", (0, i), (-1, i), bg)


def _summary_box(elements, summary: dict, styles):
    _, _, label, s = styles
    items = []
    for k, v in summary.items():
        items.append(f"<b>{k}:</b> {v}")
    text = "    |    ".join(items)
    elements.append(Paragraph(text, label))
    elements.append(Spacer(1, 0.3 * cm))


# ── Daily Roster PDF ─────────────────────────────────────────────────────────

def daily_pdf(records: list, target_date: datetime.date, company_name: str) -> bytes:
    """PDF of today's roster with shift assignments."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = _styles()
    title_st, subtitle_st, label_st, base = styles

    elements = [
        Paragraph(company_name, title_st),
        Paragraph(f"Daily Roster — {target_date.strftime('%d %B %Y')}", subtitle_st),
        HRFlowable(width="100%", thickness=1, color=HEADER_COLOR, spaceAfter=8),
    ]

    headers = ["#", "Emp ID", "Name", "Department", "Phone", "Shift", "Start", "End"]
    rows = [headers]
    for i, r in enumerate(records, 1):
        rows.append([
            str(i),
            r.get("emp_id", ""),
            r.get("emp_name", ""),
            r.get("department", ""),
            r.get("phone", ""),
            r.get("shift_name", ""),
            r.get("shift_start", ""),
            r.get("shift_end", ""),
        ])

    col_widths = [1*cm, 2*cm, 4.5*cm, 3.5*cm, 3.5*cm, 3*cm, 2*cm, 2*cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    ts = _header_table_style(len(headers))
    t.setStyle(ts)
    elements.append(t)

    _summary_footer(elements, records, label_st)
    doc.build(elements)
    return buf.getvalue()


# ── Attendance PDF ────────────────────────────────────────────────────────────

def attendance_pdf(records: list, target_date: datetime.date,
                   company_name: str) -> bytes:
    """PDF of attendance with status, worked hours, late/early minutes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = _styles()
    title_st, subtitle_st, label_st, _ = styles

    total = len(records)
    present = sum(1 for r in records if r.get("status") in ("PRESENT", "EARLY_EXIT", "OFFICE"))
    late    = sum(1 for r in records if r.get("status") == "LATE")
    absent  = sum(1 for r in records if r.get("status") == "ABSENT")
    half    = sum(1 for r in records if r.get("status") == "HALF_DAY")

    elements = [
        Paragraph(company_name, title_st),
        Paragraph(f"Attendance Report — {target_date.strftime('%d %B %Y')}", subtitle_st),
        HRFlowable(width="100%", thickness=1, color=HEADER_COLOR, spaceAfter=4),
    ]
    _summary_box(elements, {
        "Total": total, "Present": present, "Late": late,
        "Absent": absent, "Half Day": half,
    }, styles)

    headers = ["#", "Name", "Dept", "Shift Start", "Shift End",
               "In", "Out", "Worked Hrs", "Late (min)", "Status"]
    data_rows = []
    for i, r in enumerate(records, 1):
        data_rows.append([
            str(i),
            r.get("emp_name", ""),
            r.get("department", ""),
            r.get("shift_start", "—"),
            r.get("shift_end", "—"),
            r.get("first_in_str", "—"),
            r.get("last_out_str", "—"),
            str(r.get("worked_hours", "—")),
            str(r.get("late_minutes", 0)) if r.get("late_minutes") else "—",
            r.get("status", ""),
        ])

    rows = [headers] + data_rows
    col_widths = [0.7*cm, 4*cm, 3*cm, 2.2*cm, 2.2*cm, 1.8*cm, 1.8*cm, 2.2*cm, 2.2*cm, 2.5*cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    ts = _header_table_style(len(headers))
    _add_status_row_colors(ts, data_rows)
    t.setStyle(ts)
    elements.append(t)

    _generated_at(elements, label_st)
    doc.build(elements)
    return buf.getvalue()


# ── Monthly Attendance PDF ────────────────────────────────────────────────────

def monthly_pdf(records: list, year: int, month: int, company_name: str) -> bytes:
    """
    records: list of attendance dicts (same shape as daily), each with a 'date' field.
    Produces a summary table: emp_name | dept | present_days | absent_days | total_hours | avg_hours
    """
    import calendar
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = _styles()
    title_st, subtitle_st, label_st, _ = styles

    month_name = calendar.month_name[month]
    elements = [
        Paragraph(company_name, title_st),
        Paragraph(f"Monthly Attendance — {month_name} {year}", subtitle_st),
        HRFlowable(width="100%", thickness=1, color=HEADER_COLOR, spaceAfter=8),
    ]

    # Aggregate per employee
    from collections import defaultdict
    emp_data: dict = defaultdict(lambda: {
        "dept": "", "present": 0, "absent": 0, "late": 0, "total_hours": 0.0, "days": 0
    })
    for r in records:
        name = r.get("emp_name", "Unknown")
        d = emp_data[name]
        d["dept"] = r.get("department", "")
        status = r.get("status", "ABSENT")
        if status in ("PRESENT", "EARLY_EXIT", "OFFICE", "LATE"):
            d["present"] += 1
        elif status == "HALF_DAY":
            d["present"] += 1
        else:
            d["absent"] += 1
        if status == "LATE":
            d["late"] += 1
        d["total_hours"] += float(r.get("worked_hours", 0) or 0)
        d["days"] += 1

    headers = ["#", "Employee", "Department", "Present", "Absent", "Late", "Total Hrs", "Avg Hrs/Day"]
    data_rows = []
    for i, (name, d) in enumerate(sorted(emp_data.items()), 1):
        avg = round(d["total_hours"] / d["days"], 2) if d["days"] else 0
        data_rows.append([
            str(i), name, d["dept"],
            str(d["present"]), str(d["absent"]), str(d["late"]),
            str(round(d["total_hours"], 2)), str(avg),
        ])

    rows = [headers] + data_rows
    col_widths = [0.8*cm, 5*cm, 3.5*cm, 2*cm, 2*cm, 2*cm, 2.5*cm, 2.5*cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    ts = _header_table_style(len(headers))
    t.setStyle(ts)
    elements.append(t)

    _generated_at(elements, label_st)
    doc.build(elements)
    return buf.getvalue()


# ── Employee-wise PDF ─────────────────────────────────────────────────────────

def employee_pdf(records: list, emp_name: str, company_name: str) -> bytes:
    """PDF for a single employee's attendance history."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = _styles()
    title_st, subtitle_st, label_st, _ = styles

    elements = [
        Paragraph(company_name, title_st),
        Paragraph(f"Employee Attendance Report — {emp_name}", subtitle_st),
        HRFlowable(width="100%", thickness=1, color=HEADER_COLOR, spaceAfter=8),
    ]

    present = sum(1 for r in records if r.get("status") in ("PRESENT", "EARLY_EXIT", "OFFICE", "LATE"))
    absent  = sum(1 for r in records if r.get("status") == "ABSENT")
    total_h = sum(float(r.get("worked_hours", 0) or 0) for r in records)

    _summary_box(elements, {
        "Total Days": len(records), "Present": present,
        "Absent": absent, "Total Worked": f"{round(total_h, 2)} hrs",
    }, styles)

    headers = ["Date", "Shift", "Start", "End", "In", "Out", "Worked", "Status"]
    data_rows = []
    for r in sorted(records, key=lambda x: x.get("date", datetime.date.min)):
        d = r.get("date", "")
        data_rows.append([
            d.strftime("%d %b %Y") if hasattr(d, "strftime") else str(d),
            r.get("shift_name", ""),
            r.get("shift_start", "—"),
            r.get("shift_end", "—"),
            r.get("first_in_str", "—"),
            r.get("last_out_str", "—"),
            str(r.get("worked_hours", "—")),
            r.get("status", ""),
        ])

    rows = [headers] + data_rows
    col_widths = [2.5*cm, 2.5*cm, 1.8*cm, 1.8*cm, 1.8*cm, 1.8*cm, 2*cm, 2.5*cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    ts = _header_table_style(len(headers))
    _add_status_row_colors(ts, data_rows)
    t.setStyle(ts)
    elements.append(t)

    _generated_at(elements, label_st)
    doc.build(elements)
    return buf.getvalue()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _summary_footer(elements, records, label_st):
    total = len(records)
    depts = len({r.get("department") for r in records})
    elements.append(Spacer(1, 0.3*cm))
    elements.append(Paragraph(
        f"Total Employees: {total}    |    Departments: {depts}", label_st
    ))
    _generated_at(elements, label_st)


def _generated_at(elements, label_st):
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph(
        f"Generated at {datetime.datetime.now().strftime('%d %b %Y %H:%M')}",
        label_st,
    ))
