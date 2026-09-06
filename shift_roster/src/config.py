"""Central configuration loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── etimetracklite ────────────────────────────────────────────────────
    ETL_MODE: str = os.getenv("ETL_MODE", "sql")

    # SQL
    ETL_DB_DRIVER: str = os.getenv("ETL_DB_DRIVER", "mysql")
    ETL_DB_HOST: str = os.getenv("ETL_DB_HOST", "localhost")
    ETL_DB_PORT: int = int(os.getenv("ETL_DB_PORT", "3306"))
    ETL_DB_NAME: str = os.getenv("ETL_DB_NAME", "etimetracklite")
    ETL_DB_USER: str = os.getenv("ETL_DB_USER", "root")
    ETL_DB_PASSWORD: str = os.getenv("ETL_DB_PASSWORD", "")

    # API
    ETL_API_BASE_URL: str = os.getenv("ETL_API_BASE_URL", "")
    ETL_API_KEY: str = os.getenv("ETL_API_KEY", "")

    # ── Pingerbot WhatsApp ────────────────────────────────────────────────
    PINGERBOT_API_URL: str = os.getenv("PINGERBOT_API_URL", "")
    PINGERBOT_API_TOKEN: str = os.getenv("PINGERBOT_API_TOKEN", "")
    PINGERBOT_INSTANCE_ID: str = os.getenv("PINGERBOT_INSTANCE_ID", "")

    # ── Scheduler ────────────────────────────────────────────────────────
    SEND_TIME: str = os.getenv("SEND_TIME", "07:00")
    SEND_DAY_OFFSET: int = int(os.getenv("SEND_DAY_OFFSET", "0"))

    # ── Report ───────────────────────────────────────────────────────────
    MANAGER_PHONES: list = [
        p.strip()
        for p in os.getenv("MANAGER_PHONES", "").split(",")
        if p.strip()
    ]

    # ── Logging ──────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/shift_roster.log")


config = Config()
