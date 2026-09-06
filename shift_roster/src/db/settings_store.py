"""Persist runtime settings (Pingerbot credentials, manager phones) in SQLite."""
import os
from sqlalchemy import create_engine, Column, String
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Setting(Base):
    __tablename__ = "settings"
    key   = Column(String(100), primary_key=True)
    value = Column(String(500), nullable=False, default="")


_engine = None
_Session = None


def _init():
    global _engine, _Session
    if _engine:
        return
    os.makedirs("data", exist_ok=True)
    _engine = create_engine("sqlite:///data/roster.db", echo=False)
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(bind=_engine)


def get(key: str, default: str = "") -> str:
    _init()
    s = _Session()
    try:
        row = s.get(Setting, key)
        return row.value if row else default
    finally:
        s.close()


def set(key: str, value: str):
    _init()
    s = _Session()
    try:
        row = s.get(Setting, key)
        if row:
            row.value = value
        else:
            s.add(Setting(key=key, value=value))
        s.commit()
    finally:
        s.close()


def get_all() -> dict:
    _init()
    s = _Session()
    try:
        return {row.key: row.value for row in s.query(Setting).all()}
    finally:
        s.close()
