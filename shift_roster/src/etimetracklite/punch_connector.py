"""
Fetch attendance from etimetracklite (coast) database.
Uses AttendanceLogs (one row/employee/day) joined with Employees.
"""
from __future__ import annotations

import datetime
import urllib.parse
from typing import List

from src.config import config
from src.logger import get_logger

log = get_logger(__name__)


def _detect_mssql_driver() -> str:
    try:
        import pyodbc
        available = [d for d in pyodbc.drivers() if "SQL Server" in d]
        for preferred in [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "ODBC Driver 13 for SQL Server",
            "SQL Server",
        ]:
            if preferred in available:
                return preferred
        if available:
            return available[0]
    except Exception:
        pass
    return "ODBC Driver 17 for SQL Server"


def _get_engine():
    from sqlalchemy import create_engine
    driver = config.ETL_DB_DRIVER.lower()
    h, port, db = config.ETL_DB_HOST, config.ETL_DB_PORT, config.ETL_DB_NAME
    u, pw = config.ETL_DB_USER, config.ETL_DB_PASSWORD
    if driver == "mysql":
        url = f"mysql+pymysql://{u}:{pw}@{h}:{port}/{db}"
        return create_engine(url, pool_pre_ping=True)
    elif driver == "mssql":
        odbc_driver = _detect_mssql_driver()
        conn_str = (
            f"DRIVER={{{odbc_driver}}};"
            f"SERVER={h};"
            f"DATABASE={db};"
            f"UID={u};"
            f"PWD={pw};"
            "TrustServerCertificate=yes;"
        )
        log.debug("MSSQL driver=%s server=%s db=%s", odbc_driver, h, db)
        url = f"mssql+pyodbc:///?odbc_connect={urllib.parse.quote_plus(conn_str)}"
        return create_engine(url, pool_pre_ping=True)
    else:
        raise ValueError(f"Unsupported driver: {driver}")


def _to_datetime(val, date: datetime.date):
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val
    if isinstance(val, datetime.time):
        return datetime.datetime.combine(date, val)
    try:
        t = datetime.datetime.strptime(str(val).strip(), "%H:%M:%S")
        return datetime.datetime.combine(date, t.time())
    except ValueError:
        pass
    try:
        return datetime.datetime.fromisoformat(str(val))
    except ValueError:
        return None


def first_last_punches(target_date: datetime.date) -> dict:
    """
    Returns dict keyed by EmployeeCode:
        { "1": {"emp_id", "emp_name", "first_in", "last_out", "all_punches"} }
    """
    engine = _get_engine()
    query = """
        SELECT
            e.EmployeeCode  AS emp_id,
            e.EmployeeName  AS emp_name,
            a.InTime        AS first_in,
            a.OutTime       AS last_out
        FROM AttendanceLogs a
        JOIN Employees e ON e.EmployeeId = a.EmployeeId
        WHERE CAST(a.AttendanceDate AS DATE) = :target_date
    """
    summary: dict = {}
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text(query), {"target_date": target_date})
        for row in result.mappings():
            eid = str(row["emp_id"] or "").strip()
            if not eid:
                continue
            first_in = _to_datetime(row["first_in"], target_date)
            last_out = _to_datetime(row["last_out"], target_date)
            summary[eid] = {
                "emp_id":      eid,
                "emp_name":    str(row["emp_name"] or "").strip(),
                "first_in":    first_in,
                "last_out":    last_out,
                "all_punches": [t for t in [first_in, last_out] if t],
            }
    log.info("Fetched attendance for %d employees on %s", len(summary), target_date)
    return summary


def fetch_punches(target_date: datetime.date) -> List[dict]:
    """Compatibility shim — builds raw-style records from AttendanceLogs."""
    rows = []
    for rec in first_last_punches(target_date).values():
        if rec["first_in"]:
            rows.append({"emp_id": rec["emp_id"], "emp_name": rec["emp_name"],
                         "punch_time": rec["first_in"], "punch_type": "IN"})
        if rec["last_out"]:
            rows.append({"emp_id": rec["emp_id"], "emp_name": rec["emp_name"],
                         "punch_time": rec["last_out"], "punch_type": "OUT"})
    return rows
