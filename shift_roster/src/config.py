"""Central configuration loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # etimetracklite
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

    # Pingerbot WhatsApp
    PINGERBOT_BASE_URL: str = os.getenv("PINGERBOT_BASE_URL", "https://app.pingerbot.in")
    PINGERBOT_INSTANCE_ID: str = os.getenv("PINGERBOT_INSTANCE_ID", "")
    PINGERBOT_API_TOKEN: str = os.getenv("PINGERBOT_API_TOKEN", "")

    # Scheduler
    SEND_TIME: str = os.getenv("SEND_TIME", "07:00")
    SEND_DAY_OFFSET: int = int(os.getenv("SEND_DAY_OFFSET", "0"))

    # Report
    MANAGER_PHONES: list = [
        p.strip()
        for p in os.getenv("MANAGER_PHONES", "").split(",")
        if p.strip()
    ]

    # Company
    COMPANY_NAME: str = os.getenv("COMPANY_NAME", "My Company")

    # Web App
    WEB_SECRET_KEY: str = os.getenv("WEB_SECRET_KEY", "dev-secret-change-me")
    WEB_PORT: int = int(os.getenv("WEB_PORT", "5000"))
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")
    AUTHORIZED_SENDERS: list = [
        p.strip()
        for p in os.getenv("AUTHORIZED_SENDERS", "").split(",")
        if p.strip()
    ]

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/shift_roster.log")


config = Config()
