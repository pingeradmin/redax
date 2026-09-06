"""Fetch shift roster directly from the etimetracklite database."""
from __future__ import annotations

import datetime
from typing import List

from src.config import config
from src.logger import get_logger

log = get_logger(__name__)


def _get_engine():
    """Build a SQLAlchemy engine based on the configured driver."""
    from sqlalchemy import create_engine

    driver = config.ETL_DB_DRIVER.lower()
    host = config.ETL_DB_HOST
    port = config.ETL_DB_PORT
    db = config.ETL_DB_NAME
    user = config.ETL_DB_USER
    pwd = config.ETL_DB_PASSWORD

    if driver == "mysql":
        url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db}"
    elif driver == "mssql":
        url = (
            f"mssql+pyodbc://{user}:{pwd}@{host}:{port}/{db}"
            "?driver=ODBC+Driver+17+for+SQL+Server"
        )
    else:
        raise ValueError(f"Unsupported DB driver: {driver}")

    return create_engine(url, pool_pre_ping=True)


def fetch_roster(target_date: datetime.date) -> List[dict]:
    """
    Return a list of shift records for target_date.

    Each record:
        {
            "emp_id": str,
            "emp_name": str,
            "phone": str,          # with country code, e.g. "+919876543210"
            "department": str,
            "shift_code": str,
            "shift_name": str,
            "shift_start": str,    # "HH:MM"
            "shift_end": str,      # "HH:MM"
            "date": date,
        }

    NOTE: Table/column names below are typical etimetracklite defaults.
          Adjust if your installation uses custom names.
    """
    engine = _get_engine()
    query = """
        SELECT
            e.emp_id,
            e.emp_name,
            e.mobile       AS phone,
            e.department,
            s.shift_code,
            s.shift_name,
            s.in_time      AS shift_start,
            s.out_time     AS shift_end,
            rs.roster_date AS date
        FROM
            tbl_roster_schedule rs
            JOIN tbl_employee   e ON e.emp_id      = rs.emp_id
            JOIN tbl_shift      s ON s.shift_code  = rs.shift_code
        WHERE
            rs.roster_date = :target_date
        ORDER BY
            e.department, e.emp_name
    """
    rows = []
    with engine.connect() as conn:
        from sqlalchemy import text
        result = conn.execute(text(query), {"target_date": target_date})
        for row in result.mappings():
            rows.append(dict(row))

    log.info("SQL: fetched %d roster records for %s", len(rows), target_date)
    return rows
