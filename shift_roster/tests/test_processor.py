"""Unit tests for roster processor (no external dependencies needed)."""
import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.roster.processor import (
    build_employee_message,
    build_full_summary,
    group_by_department,
)


SAMPLE = [
    {
        "emp_id": "E001",
        "emp_name": "Alice",
        "phone": "+919876543210",
        "department": "Production",
        "shift_code": "A",
        "shift_name": "Morning",
        "shift_start": "06:00",
        "shift_end": "14:00",
        "date": datetime.date(2024, 6, 1),
    },
    {
        "emp_id": "E002",
        "emp_name": "Bob",
        "phone": "+919876543211",
        "department": "Security",
        "shift_code": "B",
        "shift_name": "Afternoon",
        "shift_start": "14:00",
        "shift_end": "22:00",
        "date": datetime.date(2024, 6, 1),
    },
]


def test_group_by_department():
    grouped = group_by_department(SAMPLE)
    assert "Production" in grouped
    assert "Security" in grouped
    assert len(grouped["Production"]) == 1


def test_employee_message_contains_name():
    msg = build_employee_message(SAMPLE[0])
    assert "Alice" in msg
    assert "Morning" in msg
    assert "06:00" in msg


def test_full_summary_contains_all_names():
    summary = build_full_summary(SAMPLE)
    assert "Alice" in summary
    assert "Bob" in summary
    assert "Production" in summary
    assert "Security" in summary
