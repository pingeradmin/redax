"""Fetch shift roster via the etimetracklite REST API."""
from __future__ import annotations

import datetime
from typing import List

import requests

from src.config import config
from src.logger import get_logger

log = get_logger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {config.ETL_API_KEY}",
    "Accept": "application/json",
}


def fetch_roster(target_date: datetime.date) -> List[dict]:
    """
    Calls the etimetracklite API to get the shift roster for target_date.

    Expected response shape (adjust mapping below if your API differs):
        [
            {
                "EmployeeId": "E001",
                "EmployeeName": "John Doe",
                "Mobile": "+919876543210",
                "Department": "Production",
                "ShiftCode": "A",
                "ShiftName": "Morning",
                "InTime": "06:00",
                "OutTime": "14:00",
                "RosterDate": "2024-06-01"
            },
            ...
        ]
    """
    url = f"{config.ETL_API_BASE_URL}/roster"
    params = {"date": target_date.isoformat()}

    resp = requests.get(url, headers=_HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    rows = []
    for item in data:
        rows.append({
            "emp_id":      item.get("EmployeeId", ""),
            "emp_name":    item.get("EmployeeName", ""),
            "phone":       item.get("Mobile", ""),
            "department":  item.get("Department", ""),
            "shift_code":  item.get("ShiftCode", ""),
            "shift_name":  item.get("ShiftName", ""),
            "shift_start": item.get("InTime", ""),
            "shift_end":   item.get("OutTime", ""),
            "date":        target_date,
        })

    log.info("API: fetched %d roster records for %s", len(rows), target_date)
    return rows
