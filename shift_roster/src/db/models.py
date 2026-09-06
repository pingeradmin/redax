"""SQLite database models for storing received roster data."""
import datetime
from sqlalchemy import (
    create_engine, Column, String, Date, DateTime, Integer, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class RosterEntry(Base):
    __tablename__ = "roster_entry"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    roster_date = Column(Date, nullable=False, index=True)
    emp_id      = Column(String(50), nullable=False)
    emp_name    = Column(String(150), nullable=False)
    phone       = Column(String(20), nullable=False)
    department  = Column(String(100), nullable=True)
    shift_code  = Column(String(20), nullable=True)
    shift_name  = Column(String(100), nullable=True)
    shift_start = Column(String(10), nullable=True)
    shift_end   = Column(String(10), nullable=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)
    source_msg  = Column(Text, nullable=True)   # raw WhatsApp message


class RosterReceiptLog(Base):
    """Audit log of every roster message received via WhatsApp."""
    __tablename__ = "roster_receipt_log"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    received_at = Column(DateTime, default=datetime.datetime.utcnow)
    sender      = Column(String(30), nullable=False)
    roster_date = Column(Date, nullable=True)
    raw_message = Column(Text, nullable=False)
    parsed_rows = Column(Integer, default=0)
    status      = Column(String(20), default="ok")   # ok | error | ignored


_engine = None
_Session = None


def init_db(db_path: str = "data/roster.db"):
    import os
    global _engine, _Session
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(bind=_engine)


def get_session():
    if _Session is None:
        init_db()
    return _Session()
