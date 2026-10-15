from common import db

# from flask_sqlalchemy import DeclarativeBa
from sqlalchemy import select, update

from werkzeug.security import generate_password_hash, check_password_hash

from flask_sqlalchemy.table import _Table
# from sqlalchemy.sql.dml import Update
# from sqlalchemy.sql.selectable import Select
from common import db, logger, DBBase, new_uuid7_hex
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload
from sqlalchemy import JSON, Select, ForeignKey, Integer, Float, String, DateTime, Boolean, Text, UniqueConstraint, Update, Table, Column
from sqlalchemy import select, update, func, or_, and_

from typing import Callable, Iterable, Iterator, Optional, Union, Any, Sequence, Tuple, List, cast
# from typing import get_type_hints, get_origin, get_args, Unpack
from typing_extensions import TypedDict, TypeVar ,Type
from enum import Enum
import hashlib, uuid
import random

import pathlib, mimetypes
import os
from datetime import datetime
from common import _timezone, _datetimenow

_default_email_addr_suffix = "unknown.unknown"

ModelType = TypeVar("ModelType", bound=DeclarativeBase)

def _get_birthtime(st:os.stat_result) -> Any | float:
    return getattr(st, 'st_birthtime', st.st_ctime)

def get_default_user_name(prefix:str="", suffix:str="", length:int|None=None) -> str:
    _rand_str = uuid.uuid4().hex
    
    if length is not None:
        nl = length - len(prefix) - len(suffix)
        rand_str = random.choices(_rand_str, k=min(nl, len(_rand_str)))
    else:
        rand_str = random.choices(_rand_str, k=8)

    # NOTE: random.choices() returns a *list*; it must be joined into a string,
    # otherwise f"{prefix}{rand_str}{suffix}" stringifies the list and yields
    # names like "['5', 'a', 'f', '6', ...]".
    un = f"{prefix}{''.join(rand_str)}{suffix}"

    return un

class User(DBBase):
    __tablename__ = "users"

    id :Mapped[int] = mapped_column(Integer, nullable=False, unique=True, autoincrement=True, primary_key=True)

    uuid :Mapped[str] = mapped_column(String(32), nullable=False, unique=True, default=new_uuid7_hex)
    user_name :Mapped[str] = mapped_column(String(64), nullable=False, unique=True, default=get_default_user_name)
    password_hash :Mapped[str] = mapped_column(String(256), nullable=False, unique=True)

    create_at :Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True, server_default=str(_datetimenow()))
    update_at :Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=_datetimenow)

    role_id :Mapped[int] = mapped_column(Integer, ForeignKey("user_roles.code"), default=0)
    role :Mapped["UserRole"] = relationship("UserRole", foreign_keys=[role_id])

class UserRoleEnum(Enum):
    COMMON_USER = (1, "common user")
    ADMIN = (40, "admin")

    code :int
    desc :str
    # NOTE: __new__ makes the enum *value* the int code itself, so
    # UserRoleEnum(0) resolves to WORK. Without it the member value
    # would be the whole tuple (1, "common user") and UserRoleEnum(0) raises
    # `ValueError: 0 is not a valid UserRoleEnum`.
    # `desc` defaults only for typing: EnumMeta calls __new__ with both args
    # when building members from the tuples, but lookups like
    # UserRoleEnum(code) pass a single arg.
    def __new__(cls, code: int, desc: str = "") -> "UserRoleEnum":
        obj = object.__new__(cls)
        obj._value_ = code
        obj.code = code
        obj.desc = desc
        return obj

class UserRole(DBBase):
    __tablename__ = "user_roles"

    id :Mapped[int] = mapped_column(Integer, nullable=False, unique=True, autoincrement=True, primary_key=True)

    code :Mapped[int] = mapped_column(Integer, nullable=False, unique=True)

    name :Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description :Mapped[str] = mapped_column(Text, nullable=False, default="no description")


def get_UserRole_bycode(code:int):
    stmt = select(UserRole).where(UserRole.code == code)

    return db.session.execute(stmt).scalar_one_or_none()


def create_user(password_hash:str, role:UserRole|int = UserRoleEnum.COMMON_USER.code, user_name:str|None=None) -> User|None:
    new_user = User()

    new_user.uuid = new_uuid7_hex()
    if user_name is not None and (isinstance(user_name, str) and len(user_name)>0):
        new_user.user_name = user_name

    new_user.password_hash = password_hash
    if isinstance(role, int):
        _role = get_UserRole_bycode(role)
        if _role is None:
            logger.debug(f"cannot create user with unknown role: {role}")
            return None

        new_user.role = _role
    
    db.session.add(new_user)
    db.session.commit()
    return new_user

def search_user(uuid:str|None=None, password_hash:str|None=None, role:UserRole|None=None, user_name:str|None=None) -> Sequence[User]:
    stmt = select(User)

    if uuid is not None:
        stmt = stmt.where(User.uuid == uuid)
    if password_hash is not None:
        stmt = stmt.where(User.password_hash == password_hash)
    if role is not None:
        stmt = stmt.where(User.role == role)
    if user_name is not None:
        stmt = stmt.where(User.user_name == user_name)

    rt = db.session.execute(stmt).scalars().all()
    return rt

def search_user_getone(uuid:str|None=None, password_hash:str|None=None, role:UserRole|None=None, user_name:str|None=None) ->User|None:
    stmt = select(User)

    if uuid is not None:
        stmt = stmt.where(User.uuid == uuid)
    if password_hash is not None:
        stmt = stmt.where(User.password_hash == password_hash)
    if role is not None:
        stmt = stmt.where(User.role == role)
    if user_name is not None:
        stmt = stmt.where(User.user_name == user_name)

    rt = db.session.execute(stmt.limit(1)).scalars().all()
    if rt:
        return rt[0]

    return None


def verify_user_password(user: User, password: str) -> bool:
    """Verify ``password`` against the user's stored hash, transparently
    upgrading legacy unsalted sha256 hashes (pre-2026-09 accounts) to the
    current salted werkzeug format on a successful login."""
    stored = user.password_hash or ""
    if "$" in stored:
        # salted werkzeug format (scrypt/pbkdf2): verify directly
        return check_password_hash(stored, password)

    return False