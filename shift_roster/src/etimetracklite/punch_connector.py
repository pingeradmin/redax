"""
Fetch punch records from the eSSL / etimetracklite SQL database.

Common eSSL table names (adjust in .env if yours differ):
  ESSL_PUNCH_TABLE   = iclock_transaction   (ZKTeco / eSSL default)
                     OR tbl_punchdata        (older etimetracklite)
  ESSL_EMP_TABLE     = hr_employee          (ZKTeco)
                     OR tbl_employee         (etimetracklite)

Typical punch record columns:
  emp_code / emp_id      Employee ID
  punch_time             Full datetime of punch
  punch_state            0=Check-In  1=Check-Out  (ZKTeco)
  direction              'I'=In  'O'=Out           (older eSSL)
"""
from __future__ import annotations

import datetime
import os
from typing import List

from src.config import config
from src.logger import get_logger

log = get_logger(__name__)

# Override these in .env if your tables/columns are named differently
PUNCH_TABLE = os.getenv("ESSL_PUNCH_TABLE", "iclock_transaction")
EMP_TABLE   = os.getenv("ESSL_EMP_TABLE",   "hr_employee")
EMP_ID_COL  = os.getenv("ESSL_EMP_ID_COL",  "emp_code")    # column in both tables
EMP_NAME_COL = os.getenv("ESSL_EMP_NAME_COL", "emp_name")
PUNCH_TIME_COL  = os.getenv("ESSL_PUNCH_TIME_COL", "punch_time")
PUNCH_STATE_COL = os.getenv("ESSL_PUNCH_STATE_COL", "punch_state")  # 0=in 1=out


def _get_engine():
    from sqlalchemy import create_engine
    driver = config.ETL_DB_DRIVER.lower()
    h, port, db = config.ETL_DB_HOST, config.ETL_DB_PORT, config.ETL_DB_NAME
    u, pw = config.ETL_DB_USER, config.ETL_DB_PASSWORD

    if driver == "mysql":
        url = f"mysql+pymysql://{u}:{pw}@{h}:{port}/{db}"
    elif driver == "mssql":
        url = (
            f"mssql+pyodbc://{u}:{pw}@{h}:{port}/{db}"
            "?driver=ODBC+Driver+17+for+SQL+Server"
        )
    else:
        raise ValueError(f"Unsupported driver: {driver}")

    return create_engine(url, pool_pre_ping=True)


def fetch_punches(target_date: datetime.date) -> List[dict]:
    """
    Return all punch records for target_date.

    Each record:
        {
            "emp_id":     str,
            "emp_name":   str,
            "punch_time": datetime,
            "punch_type": "IN" | "OUT" | "UNKNOWN",
        }
    """
    engine = _get_engine()

    # Build date range: full day
    day_start = datetime.datetime.combine(target_date, datetime.time.min)
    day_end   = datetime.datetime.combine(target_date, datetime.time.max)

    query = f"""
        SELECT
            t.{EMP_ID_COL}     AS emp_id,
            e.{EMP_NAME_COL}   AS emp_name,
            t.{PUNCH_TIME_COL} AS punch_time,
            t.{PUNCH_STATE_COL} AS punch_state
        FROM
            {PUNCH_TABLE} t
            LEFT JOIN {EMP_TABLE} e ON e.{EMP_ID_COL} = t.{EMP_ID_COL}
        WHERE
            t.{PUNCH_TIME_COL} BETWEEN :day_start AND :day_end
        ORDER BY
            t.{EMP_ID_COL}, t.{PUNCH_TIME_COL}
    """

    rows = []
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(
            text(query),
            {"day_start": day_start, "day_end": day_end},
        )
        for row in result.mappings():
            state = str(row.get("punch_state", "")).strip()
            # Normalise punch direction
            if state in ("0", "I", "in", "IN", "check_in"):
                ptype = "IN"
            elif state in ("1", "O", "out", "OUT", "check_out"):
                ptype = "OUT"
            else:
                ptype = "UNKNOWN"

            rows.append({
                "emp_id":     str(row["emp_id"]).strip(),
                "emp_name":   str(row.get("emp_name") or "").strip(),
                "punch_time": row["punch_time"],
                "punch_type": ptype,
            })

    log.info("Fetched %d punch records for %s", len(rows), target_date)
    return rows


def first_last_punches(target_date: datetime.date) -> dict:
    """
    Returns a dict keyed by emp_id with their first IN and last OUT for the day.

        {
            "E001": {
                "emp_id":    "E001",
                "emp_name":  "Alice",
                "first_in":  datetime | None,
                "last_out":  datetime | None,
                "all_punches": [datetime, ...],
            },
            ...
        }
    """
    punches = fetch_punches(target_date)
    summary: dict = {}

    for p in punches:
        eid = p["emp_id"]
        if eid not in summary:
            summary[eid] = {
                "emp_id":     eid,
                "emp_name":   p["emp_name"],
                "first_in":   None,
                "last_out":   None,
                "all_punches": [],
            }
        rec = summary[eid]
        rec["all_punches"].append(p["punch_time"])

        if p["punch_type"] == "IN":
            if rec["first_in"] is None or p["punch_time"] < rec["first_in"]:
                rec["first_in"] = p["punch_time"]
        elif p["punch_type"] == "OUT":
            if rec["last_out"] is None or p["punch_time"] > rec["last_out"]:
                rec["last_out"] = p["punch_time"]

    # For devices that don't distinguish IN/OUT (all UNKNOWN),
    # fall back: earliest punch = IN, latest punch = OUT
    for rec in summary.values():
        if rec["first_in"] is None and rec["all_punches"]:
            rec["first_in"]  = min(rec["all_punches"])
            rec["last_out"]  = max(rec["all_punches"])

    return summary
