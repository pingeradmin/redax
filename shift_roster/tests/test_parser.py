"""Tests for the roster message parser."""
import sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.roster.parser import parse_roster_message


def test_pipe_format():
    msg = (
        "ROSTER 2024-06-15\n"
        "E001|Alice|+919876543210|Production|A|Morning|06:00|14:00\n"
        "E002|Bob|+919876543211|Security|B|Afternoon|14:00|22:00"
    )
    date, records = parse_roster_message(msg)
    assert date == datetime.date(2024, 6, 15)
    assert len(records) == 2
    assert records[0]["emp_name"] == "Alice"
    assert records[0]["shift_start"] == "06:00"
    assert records[1]["emp_name"] == "Bob"


def test_simple_format():
    msg = (
        "Roster for 15-06-2024\n"
        "Alice +919876543210 Morning 06:00 14:00\n"
        "Bob +919876543211 Afternoon 14:00 22:00"
    )
    date, records = parse_roster_message(msg)
    assert date == datetime.date(2024, 6, 15)
    assert len(records) == 2


def test_department_grouped_format():
    msg = (
        "Shift Roster 2024-06-15\n"
        "[Production]\n"
        "Alice +919876543210 Morning 06:00 14:00\n"
        "[Security]\n"
        "Bob +919876543211 Night 22:00 06:00"
    )
    date, records = parse_roster_message(msg)
    assert date == datetime.date(2024, 6, 15)
    assert len(records) == 2
    prod = [r for r in records if r["department"] == "Production"]
    sec  = [r for r in records if r["department"] == "Security"]
    assert len(prod) == 1
    assert len(sec) == 1


def test_no_date_returns_empty():
    date, records = parse_roster_message("Alice +919876543210 Morning 06:00 14:00")
    assert date is None
    assert records == []


def test_empty_message():
    date, records = parse_roster_message("")
    assert date is None
    assert records == []
