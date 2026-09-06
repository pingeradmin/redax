"""
Fetch attendance from etimetracklite (coast) database.

Primary source : AttendanceLogs (one processed row/employee/day)
Fallback source: DeviceLogs_{M}_{YYYY} (raw device punches for current month)
                 used when AttendanceLogs has not yet been processed for the date.
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


def _from_attendance_logs(target_date: datetime.date, engine) -> dict:
    """Read from AttendanceLogs (processed attendance, one row/employee/day)."""
    from sqlalchemy import text
    query = """
        SELECT
            CAST(e.EmployeeCode AS VARCHAR(50)) AS emp_id,
            e.EmployeeName                       AS emp_name,
            a.InTime                             AS first_in,
            a.OutTime                            AS last_out
        FROM AttendanceLogs a
        JOIN Employees e ON e.EmployeeId = a.EmployeeId
        WHERE CAST(a.AttendanceDate AS DATE) = :target_date
    """
    summary: dict = {}
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
    log.info("AttendanceLogs: %d employees for %s", len(summary), target_date)
    return summary


def _from_device_logs(target_date: datetime.date, engine) -> dict:
    """
    Fallback: read raw punches from DeviceLogs_{M}_{YYYY}.
    UserId in DeviceLogs maps to EmployeeCode in Employees.
    AttDirection: 'in' / 'out' (or empty — then use min/max).
    """
    table = f"DeviceLogs_{target_date.month}_{target_date.year}"
    from sqlalchemy import text

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = :t"),
            {"t": table},
        ).scalar()
        if not exists:
            log.warning("Device log table %s not found", table)
            return {}

        query = f"""
            SELECT
                d.UserId      AS user_id,
                e.EmployeeName AS emp_name,
                d.LogDate      AS punch_time,
                d.AttDirection AS direction
            FROM {table} d
            LEFT JOIN Employees e
                   ON CAST(e.EmployeeCode AS VARCHAR(50)) = d.UserId
                   OR e.EmployeeCodeInDevice = d.UserId
            WHERE CAST(d.LogDate AS DATE) = :target_date
            ORDER BY d.UserId, d.LogDate
        """
        result = conn.execute(text(query), {"target_date": target_date})

        summary: dict = {}
        for row in result.mappings():
            eid = str(row["user_id"] or "").strip()
            if not eid:
                continue
            if eid not in summary:
                summary[eid] = {
                    "emp_id":      eid,
                    "emp_name":    str(row["emp_name"] or "").strip(),
                    "first_in":    None,
                    "last_out":    None,
                    "all_punches": [],
                }
            rec = summary[eid]
            pt = row["punch_time"]
            if pt is None:
                continue
            rec["all_punches"].append(pt)

            direction = str(row["direction"] or "").lower().strip()
            if direction in ("in", "i", "0", "check_in"):
                if rec["first_in"] is None or pt < rec["first_in"]:
                    rec["first_in"] = pt
            elif direction in ("out", "o", "1", "check_out"):
                if rec["last_out"] is None or pt > rec["last_out"]:
                    rec["last_out"] = pt

        # Devices that don't distinguish in/out: earliest=IN, latest=OUT
        for rec in summary.values():
            if rec["first_in"] is None and rec["all_punches"]:
                rec["first_in"] = min(rec["all_punches"])
                rec["last_out"] = max(rec["all_punches"])

    log.info("DeviceLogs fallback (%s): %d employees for %s", table, len(summary), target_date)
    return summary


def first_last_punches(target_date: datetime.date) -> dict:
    """
    Returns dict keyed by employee code:
        { "12": {"emp_id", "emp_name", "first_in", "last_out", "all_punches"} }

    Tries AttendanceLogs first; falls back to DeviceLogs_{M}_{YYYY} when
    AttendanceLogs has not yet been processed for the requested date.
    """
    engine = _get_engine()
    summary = _from_attendance_logs(target_date, engine)
    if not summary:
        log.info("AttendanceLogs empty for %s — trying DeviceLogs fallback", target_date)
        summary = _from_device_logs(target_date, engine)
    return summary


def sync_employees() -> List[dict]:
    """
    Fetch all active employees from ESSL Employees + Departments.
    Returns list of dicts: {emp_code, emp_name, department, phone}
    """
    engine = _get_engine()
    # Try joining Departments; gracefully fall back if column name differs
    queries = [
        """
        SELECT
            CAST(e.EmployeeCode AS VARCHAR(50)) AS emp_code,
            e.EmployeeName   AS emp_name,
            d.DepartmentName AS department,
            e.ContactNo      AS phone
        FROM Employees e
        LEFT JOIN Departments d ON d.DepartmentId = e.DepartmentId
        WHERE e.RecordStatus = 1
        ORDER BY e.EmployeeCode
        """,
        # fallback if DepartmentName column differs
        """
        SELECT
            CAST(e.EmployeeCode AS VARCHAR(50)) AS emp_code,
            e.EmployeeName AS emp_name,
            NULL           AS department,
            e.ContactNo    AS phone
        FROM Employees e
        WHERE e.RecordStatus = 1
        ORDER BY e.EmployeeCode
        """,
    ]
    from sqlalchemy import text
    rows = []
    with engine.connect() as conn:
        for q in queries:
            try:
                result = conn.execute(text(q))
                for row in result.mappings():
                    rows.append({
                        "emp_code":   str(row["emp_code"] or "").strip(),
                        "emp_name":   str(row["emp_name"] or "").strip(),
                        "department": str(row["department"] or "").strip(),
                        "phone":      str(row["phone"] or "").strip(),
                    })
                break  # success
            except Exception as exc:
                log.warning("Employee query failed, trying fallback: %s", exc)
                rows = []
    log.info("Synced %d employees from ESSL", len(rows))
    return rows


def fetch_punches(target_date: datetime.date) -> List[dict]:
    """Compatibility shim — returns raw-style IN/OUT records."""
    rows = []
    for rec in first_last_punches(target_date).values():
        if rec["first_in"]:
            rows.append({"emp_id": rec["emp_id"], "emp_name": rec["emp_name"],
                         "punch_time": rec["first_in"], "punch_type": "IN"})
        if rec["last_out"]:
            rows.append({"emp_id": rec["emp_id"], "emp_name": rec["emp_name"],
                         "punch_time": rec["last_out"], "punch_type": "OUT"})
    return rows
