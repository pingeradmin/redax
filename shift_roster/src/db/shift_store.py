"""CRUD helpers for CustomShift."""
from __future__ import annotations

from typing import List, Optional

from src.db.models import CustomShift, get_session
from src.logger import get_logger

log = get_logger(__name__)


def get_all_shifts(active_only: bool = False) -> List[CustomShift]:
    sess = get_session()
    try:
        q = sess.query(CustomShift)
        if active_only:
            q = q.filter_by(active=True)
        return q.order_by(CustomShift.name).all()
    finally:
        sess.close()


def get_shift_by_id(shift_id: int) -> Optional[CustomShift]:
    sess = get_session()
    try:
        return sess.query(CustomShift).filter_by(id=shift_id).first()
    finally:
        sess.close()


def create_shift(name: str, start_time: str, end_time: str,
                 code: str = "", department: str = "") -> CustomShift:
    sess = get_session()
    try:
        shift = CustomShift(
            name=name, code=code, start_time=start_time,
            end_time=end_time, department=department, active=True,
        )
        sess.add(shift)
        sess.commit()
        sess.refresh(shift)
        log.info("Created shift %s (%s-%s)", name, start_time, end_time)
        return shift
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def update_shift(shift_id: int, name: str = None, code: str = None,
                 start_time: str = None, end_time: str = None,
                 department: str = None, active: bool = None) -> bool:
    sess = get_session()
    try:
        shift = sess.query(CustomShift).filter_by(id=shift_id).first()
        if not shift:
            return False
        if name is not None:
            shift.name = name
        if code is not None:
            shift.code = code
        if start_time is not None:
            shift.start_time = start_time
        if end_time is not None:
            shift.end_time = end_time
        if department is not None:
            shift.department = department
        if active is not None:
            shift.active = active
        sess.commit()
        return True
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def delete_shift(shift_id: int) -> bool:
    sess = get_session()
    try:
        shift = sess.query(CustomShift).filter_by(id=shift_id).first()
        if not shift:
            return False
        sess.delete(shift)
        sess.commit()
        return True
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
