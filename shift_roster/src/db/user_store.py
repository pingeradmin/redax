"""CRUD helpers for AppUser."""
from __future__ import annotations

import datetime
from typing import List, Optional

from werkzeug.security import generate_password_hash, check_password_hash

from src.db.models import AppUser, get_session
from src.logger import get_logger

log = get_logger(__name__)

ROLES = ("admin", "manager", "viewer")


def get_all_users() -> List[AppUser]:
    sess = get_session()
    try:
        return sess.query(AppUser).order_by(AppUser.username).all()
    finally:
        sess.close()


def get_user_by_id(user_id: int) -> Optional[AppUser]:
    sess = get_session()
    try:
        return sess.query(AppUser).filter_by(id=user_id).first()
    finally:
        sess.close()


def get_user_by_username(username: str) -> Optional[AppUser]:
    sess = get_session()
    try:
        return sess.query(AppUser).filter_by(username=username).first()
    finally:
        sess.close()


def create_user(username: str, password: str, full_name: str = "",
                role: str = "viewer") -> AppUser:
    sess = get_session()
    try:
        user = AppUser(
            username=username,
            password_hash=generate_password_hash(password),
            full_name=full_name,
            role=role,
            active=True,
        )
        sess.add(user)
        sess.commit()
        sess.refresh(user)
        log.info("Created user %s (role=%s)", username, role)
        return user
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def update_user(user_id: int, full_name: str = None, role: str = None,
                active: bool = None, password: str = None) -> bool:
    sess = get_session()
    try:
        user = sess.query(AppUser).filter_by(id=user_id).first()
        if not user:
            return False
        if full_name is not None:
            user.full_name = full_name
        if role is not None and role in ROLES:
            user.role = role
        if active is not None:
            user.active = active
        if password:
            user.password_hash = generate_password_hash(password)
        sess.commit()
        return True
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def delete_user(user_id: int) -> bool:
    sess = get_session()
    try:
        user = sess.query(AppUser).filter_by(id=user_id).first()
        if not user:
            return False
        sess.delete(user)
        sess.commit()
        return True
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def authenticate(username: str, password: str) -> Optional[AppUser]:
    user = get_user_by_username(username)
    if user and user.active and check_password_hash(user.password_hash, password):
        sess = get_session()
        try:
            u = sess.query(AppUser).filter_by(id=user.id).first()
            u.last_login = datetime.datetime.utcnow()
            sess.commit()
        finally:
            sess.close()
        return user
    return None
