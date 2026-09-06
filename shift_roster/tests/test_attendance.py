"""Tests for attendance analyser — no DB connection needed."""
import sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.roster.attendance import analyse, attendance_whatsapp_report

DATE = datetime.date(2024, 6, 15)

ROSTER = [
    {
        "date": DATE, "emp_id": "E001", "emp_name": "Alice",
        "phone": "+919876543210", "department": "Production",
        "shift_code": "A", "shift_name": "Morning",
        "shift_start": "06:00", "shift_end": "14:00",
    },
    {
        "date": DATE, "emp_id": "E002", "emp_name": "Bob",
        "phone": "+919876543211", "department": "Security",
        "shift_code": "B", "shift_name": "Afternoon",
        "shift_start": "14:00", "shift_end": "22:00",
    },
    {
        "date": DATE, "emp_id": "E003", "emp_name": "Carol",
        "phone": "+919876543212", "department": "Production",
        "shift_code": "A", "shift_name": "Morning",
        "shift_start": "06:00", "shift_end": "14:00",
    },
]

def _dt(h, m):
    return datetime.datetime(2024, 6, 15, h, m)


def test_present_on_time():
    punches = {
        "E001": {"emp_id": "E001", "emp_name": "Alice",
                 "first_in": _dt(5, 55), "last_out": _dt(14, 5), "all_punches": []},
    }
    results = {r["emp_id"]: r for r in analyse(ROSTER[:1], punches)}
    assert results["E001"]["status"] == "PRESENT"
    assert results["E001"]["late_minutes"] == 0


def test_late_arrival():
    punches = {
        "E001": {"emp_id": "E001", "emp_name": "Alice",
                 "first_in": _dt(6, 30), "last_out": _dt(14, 5), "all_punches": []},
    }
    results = {r["emp_id"]: r for r in analyse(ROSTER[:1], punches)}
    assert results["E001"]["status"] == "LATE"
    assert results["E001"]["late_minutes"] == 30


def test_absent():
    results = {r["emp_id"]: r for r in analyse(ROSTER[:1], {})}
    assert results["E001"]["status"] == "ABSENT"


def test_early_exit():
    punches = {
        "E001": {"emp_id": "E001", "emp_name": "Alice",
                 "first_in": _dt(6, 0), "last_out": _dt(12, 0), "all_punches": []},
    }
    results = {r["emp_id"]: r for r in analyse(ROSTER[:1], punches)}
    assert results["E001"]["status"] == "EARLY_EXIT"
    assert results["E001"]["early_exit_minutes"] == 120


def test_whatsapp_report_contains_counts():
    punches = {
        "E001": {"emp_id": "E001", "emp_name": "Alice",
                 "first_in": _dt(5, 55), "last_out": _dt(14, 5), "all_punches": []},
        "E002": {"emp_id": "E002", "emp_name": "Bob",
                 "first_in": _dt(14, 20), "last_out": _dt(22, 0), "all_punches": []},
        # E003 absent
    }
    records = analyse(ROSTER, punches)
    report = attendance_whatsapp_report(records, DATE)
    assert "Absent" in report
    assert "Carol" in report     # absent employee listed
    assert "Late" in report
