"""Unified entry point — delegates to SQL or API connector based on config."""
from __future__ import annotations

import datetime
from typing import List

from src.config import config
from src.logger import get_logger

log = get_logger(__name__)


def fetch_roster(target_date: datetime.date) -> List[dict]:
    mode = config.ETL_MODE.lower()
    if mode == "sql":
        from src.etimetracklite.sql_connector import fetch_roster as _fetch
    elif mode == "api":
        from src.etimetracklite.api_connector import fetch_roster as _fetch
    else:
        raise ValueError(f"Unknown ETL_MODE '{mode}'. Use 'sql' or 'api'.")

    return _fetch(target_date)
