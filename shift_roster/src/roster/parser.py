"""
Parse shift roster from a WhatsApp text message.

Supported formats (auto-detected):

FORMAT 1 — Pipe/comma delimited (most reliable, recommended):
    ROSTER 2024-06-15
    E001|Alice|+919876543210|Production|A|Morning|06:00|14:00
    E002|Bob|+919876543211|Security|B|Afternoon|14:00|22:00

FORMAT 2 — Simple list (no emp_id, no dept):
    Roster for 15-06-2024
    Alice +919876543210 Morning 06:00 14:00
    Bob +919876543211 Afternoon 14:00 22:00

FORMAT 3 — Department-grouped:
    Roster 15/06/2024
    [Production]
    Alice +919876543210 Morning 06:00-14:00
    [Security]
    Bob +919876543211 Night 22:00-06:00

The date line is required in all formats.
"""
from __future__ import annotations

import datetime
import re
from typing import List, Optional, Tuple


_DATE_PATTERNS = [
    r"(\d{4}-\d{2}-\d{2})",                # 2024-06-15
    r"(\d{2}[/\-.]\d{2}[/\-.]\d{4})",     # 15-06-2024 or 15/06/2024 or 15.06.2024
    r"(\d{2}[/\-.]\d{2}[/\-.]\d{2})",     # 15/06/24 or 15.06.24
    r"(\d{1,2}\s+\w+\s+\d{4})",            # 15 June 2024
]

_TIME_RE = re.compile(r"\b(\d{1,2}[:.]\d{2})\b")
_PHONE_RE = re.compile(r"\+?\d{10,15}")
_DEPT_HEADER_RE = re.compile(r"^\[(.+)\]$")

_SHIFT_KEYWORDS = {"morning", "afternoon", "evening", "night", "general"}


def _normalise_time(t: str) -> str:
    return t.replace(".", ":")


def _parse_date(text: str) -> Optional[datetime.date]:
    for pat in _DATE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1)
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
                        "%d-%m-%y", "%d/%m/%y", "%d.%m.%y",
                        "%d %B %Y", "%d %b %Y"):
                try:
                    return datetime.datetime.strptime(raw, fmt).date()
                except ValueError:
                    continue
    return None


def _is_date_line(line: str) -> bool:
    lower = line.lower()
    keywords = ("roster", "date", "shift", "schedule", "rota")
    has_keyword = any(k in lower for k in keywords)
    has_date = any(re.search(p, line) for p in _DATE_PATTERNS)
    return has_date and (has_keyword or line.strip().startswith(tuple("0123456789")))


def _parse_pipe_row(line: str, target_date: datetime.date) -> Optional[dict]:
    """Parse: E001|Alice|+91...|Dept|Code|ShiftName|HH:MM|HH:MM"""
    sep = "|" if "|" in line else ","
    parts = [p.strip() for p in line.split(sep)]
    if len(parts) < 4:
        return None
    times = [_normalise_time(t) for t in _TIME_RE.findall(line)]
    return {
        "date":        target_date,
        "emp_id":      parts[0] if len(parts) > 0 else "",
        "emp_name":    parts[1] if len(parts) > 1 else "",
        "phone":       _normalise_phone(parts[2]) if len(parts) > 2 else "",
        "department":  parts[3] if len(parts) > 3 else "",
        "shift_code":  parts[4] if len(parts) > 4 else "",
        "shift_name":  parts[5] if len(parts) > 5 else "",
        "shift_start": times[0] if len(times) > 0 else "",
        "shift_end":   times[1] if len(times) > 1 else "",
    }


def _parse_simple_row(line: str, target_date: datetime.date,
                       department: str = "") -> Optional[dict]:
    """Parse: Alice +919876543210 Morning 06:00 14:00
    Also: saravana kumar morning 9.00 6.00  (no phone, dot times)
    """
    phones = _PHONE_RE.findall(line)
    times = [_normalise_time(t) for t in _TIME_RE.findall(line)]
    if len(times) < 2:
        return None

    phone = _normalise_phone(phones[0]) if phones else ""

    # Remove phone and times from line to isolate name+shift parts
    cleaned = _PHONE_RE.sub("", line)
    cleaned = _TIME_RE.sub("", cleaned)
    # Remove separators like dash or em-dash
    cleaned = re.sub(r"[-–—|,]", " ", cleaned)
    tokens = [t for t in cleaned.split() if t]

    if not tokens:
        return None

    # Split on first known shift keyword; everything before is name, after is shift
    name_parts, shift_parts = [], []
    in_shift = False
    for t in tokens:
        if t.lower() in _SHIFT_KEYWORDS:
            in_shift = True
        if in_shift:
            shift_parts.append(t)
        else:
            name_parts.append(t)

    # Fallback: no shift keyword found — last token is shift name, rest is emp name
    if not shift_parts and name_parts:
        shift_parts = [name_parts.pop()]

    emp_name = " ".join(name_parts).title() if name_parts else "Unknown"
    shift_name = " ".join(shift_parts).strip() if shift_parts else ""

    return {
        "date":        target_date,
        "emp_id":      "",
        "emp_name":    emp_name,
        "phone":       phone,
        "department":  department,
        "shift_code":  "",
        "shift_name":  shift_name,
        "shift_start": times[0],
        "shift_end":   times[1],
    }


def _normalise_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return "+91" + digits          # assume India if 10 digits
    if len(digits) > 10:
        return "+" + digits
    return raw


def parse_roster_message(message: str) -> Tuple[Optional[datetime.date], List[dict]]:
    """
    Main entry point.

    Returns:
        (roster_date, records)   — records is [] if parsing fails.
    """
    lines = [l.strip() for l in message.strip().splitlines() if l.strip()]
    if not lines:
        return None, []

    # Find date
    target_date: Optional[datetime.date] = None
    for line in lines:
        target_date = _parse_date(line)
        if target_date:
            break

    if not target_date:
        return None, []

    # Detect format: pipe/comma → FORMAT 1; department headers → FORMAT 3; else FORMAT 2
    has_pipe = any("|" in l for l in lines)
    has_dept_header = any(_DEPT_HEADER_RE.match(l) for l in lines)

    records: List[dict] = []

    if has_pipe:
        for line in lines:
            if "|" not in line:
                continue
            if _parse_date(line):
                continue
            rec = _parse_pipe_row(line, target_date)
            if rec:
                records.append(rec)

    elif has_dept_header:
        current_dept = ""
        for line in lines:
            dm = _DEPT_HEADER_RE.match(line)
            if dm:
                current_dept = dm.group(1).strip()
                continue
            if _parse_date(line):
                continue
            rec = _parse_simple_row(line, target_date, current_dept)
            if rec:
                records.append(rec)

    else:
        for line in lines:
            if _parse_date(line) and any(
                k in line.lower() for k in ("roster", "date", "shift", "schedule")
            ):
                continue
            rec = _parse_simple_row(line, target_date)
            if rec:
                records.append(rec)

    return target_date, records
