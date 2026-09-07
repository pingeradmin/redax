"""SQLite database models for storing received roster data."""
import datetime
from sqlalchemy import (
    create_engine, Column, String, Date, DateTime, Integer, Text, Boolean, Float,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class RosterEntry(Base):
    __tablename__ = "roster_entry"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    roster_date = Column(Date, nullable=False, index=True)
    emp_id      = Column(String(50), nullable=False)
    emp_name    = Column(String(150), nullable=False)
    phone       = Column(String(20), nullable=True)
    department  = Column(String(100), nullable=True)
    shift_code  = Column(String(20), nullable=True)
    shift_name  = Column(String(100), nullable=True)
    shift_start = Column(String(10), nullable=True)
    shift_end   = Column(String(10), nullable=True)
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)
    source_msg  = Column(Text, nullable=True)


class Employee(Base):
    """Local cache of employees synced from ESSL database."""
    __tablename__ = "employee"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    emp_code   = Column(String(50), unique=True, nullable=False, index=True)
    emp_name   = Column(String(150), nullable=False)
    department = Column(String(100), nullable=True)
    phone      = Column(String(20), nullable=True)
    status     = Column(String(20), default="active")
    synced_at  = Column(DateTime, default=datetime.datetime.utcnow)


class RosterReceiptLog(Base):
    """Audit log of every roster message received via WhatsApp."""
    __tablename__ = "roster_receipt_log"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    received_at = Column(DateTime, default=datetime.datetime.utcnow)
    sender      = Column(String(30), nullable=False)
    roster_date = Column(Date, nullable=True)
    raw_message = Column(Text, nullable=False)
    parsed_rows = Column(Integer, default=0)
    status      = Column(String(20), default="ok")


class AppUser(Base):
    """Application users with role-based access."""
    __tablename__ = "app_user"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    username      = Column(String(80), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    full_name     = Column(String(150), nullable=True)
    role          = Column(String(20), default="viewer")   # admin | manager | viewer
    active        = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.datetime.utcnow)
    last_login    = Column(DateTime, nullable=True)


class CustomShift(Base):
    """Custom shift definitions (independent of WhatsApp roster)."""
    __tablename__ = "custom_shift"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(String(100), nullable=False)
    code       = Column(String(20), nullable=True)
    start_time = Column(String(10), nullable=False)   # HH:MM
    end_time   = Column(String(10), nullable=False)   # HH:MM
    department = Column(String(100), nullable=True)
    active     = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


_engine = None
_Session = None


def init_db(db_path: str = "data/roster.db"):
    import os
    global _engine, _Session
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(bind=_engine)
    _seed_default_admin()


def _seed_default_admin():
    """Create the default admin user if no users exist yet."""
    from src.config import config
    from werkzeug.security import generate_password_hash
    sess = _Session()
    try:
        if sess.query(AppUser).count() == 0:
            sess.add(AppUser(
                username=config.ADMIN_USERNAME,
                password_hash=generate_password_hash(config.ADMIN_PASSWORD),
                full_name="Administrator",
                role="admin",
                active=True,
            ))
            sess.commit()
    except Exception:
        sess.rollback()
    finally:
        sess.close()


def get_session():
    if _Session is None:
        init_db()
    return _Session()
