import pathlib
import os
import json
import logging
from concurrent_log_handler import ConcurrentTimedRotatingFileHandler

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_babel import Babel
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData, event, Engine
from sqlite3 import Connection as SQLite3Connection

from typing import Any, Sequence, cast
import uuid, time

from zoneinfo import ZoneInfo
from datetime import datetime
_timezone = ZoneInfo("Asia/Shanghai")
_datetimenow = lambda: datetime.now(_timezone)

app_root = pathlib.Path(__file__).parent.resolve()
ENCODING = 'utf-8'


# ---- UUIDv7 (RFC 9562) ----
# We always generate version-7 ids, on every interpreter:
#  * Python >= 3.14 provides uuid.uuid7() in the stdlib;
#  * older interpreters use the pure-Python replica below, which mirrors
#    CPython 3.14's uuid.uuid7() byte-for-byte in format.
# uuid7 ids embed a 48-bit unix-ms timestamp and sort in creation order
# (RFC 9562 Method 1: monotonic 42-bit counter + 32-bit random tail), so
# unlike uuid4 they keep index locality and stay usable as time-ordered
# primary keys (e.g. PostgreSQL) later.

_uuid7_last_timestamp: int | None = None
_uuid7_last_counter: int | None = None


def _uuid7_counter_and_tail() -> tuple[int, int]:
    """42-bit counter with MSB=0 plus 32-bit random tail (CPython 3.14)."""
    rand = int.from_bytes(os.urandom(10))
    counter = (rand >> 32) & 0x1ff_ffff_ffff
    tail = rand & 0xffff_ffff
    return counter, tail


def _uuid7_hex_fallback() -> str:
    """Pure-Python UUIDv7 hex, replicating CPython 3.14's uuid.uuid7().

    Layout: 48-bit unix_ts_ms | 4-bit version(7) | 12-bit counter_hi |
    2-bit variant(10) | 30-bit counter_lo | 32-bit random tail.
    Monotonic within a millisecond: when several ids are generated in the
    same millisecond the counter is incremented; on overflow the timestamp
    is advanced and the counter is re-randomized.
    """
    global _uuid7_last_timestamp, _uuid7_last_counter

    nanoseconds = time.time_ns()
    timestamp_ms = nanoseconds // 1_000_000

    if _uuid7_last_timestamp is None or timestamp_ms > _uuid7_last_timestamp:
        counter, tail = _uuid7_counter_and_tail()
    else:
        if timestamp_ms < _uuid7_last_timestamp:
            timestamp_ms = _uuid7_last_timestamp + 1
        # advance the 42-bit counter (the counter is always set whenever
        # the timestamp is set, so this can not be None here)
        assert _uuid7_last_counter is not None
        counter = _uuid7_last_counter + 1
        if counter > 0x3ff_ffff_ffff:
            # advance the 48-bit timestamp and re-randomize
            timestamp_ms += 1
            counter, tail = _uuid7_counter_and_tail()
        else:
            # 32-bit random data
            tail = int.from_bytes(os.urandom(4))

    unix_ts_ms = timestamp_ms & 0xffff_ffff_ffff
    counter_hi = (counter >> 30) & 0x0fff
    counter_lo = counter & 0x3fff_ffff
    tail &= 0xffff_ffff

    int_uuid = unix_ts_ms << 80
    int_uuid |= counter_hi << 64
    int_uuid |= counter_lo << 32
    int_uuid |= tail
    int_uuid |= (7 << 76) | (0b10 << 62)  # version 7 + RFC 4122 variant

    _uuid7_last_timestamp = timestamp_ms
    _uuid7_last_counter = counter
    return f"{int_uuid:032x}"


def new_uuid7_hex() -> str:
    """Return a 32-char lowercase hex UUIDv7 (RFC 9562).

    Always version 7, regardless of the Python version running: uses the
    stdlib uuid.uuid7() on Python >= 3.14 and the pure-Python replica
    above on older interpreters.
    """
    uuid7: Any = getattr(uuid, "uuid7", None)
    if uuid7 is not None:
        return cast(str, uuid7().hex)
    return _uuid7_hex_fallback()


log_dir = app_root / "log"
log_file = log_dir / "log.txt"
data_dir = app_root / "data"
user_data_path = data_dir / "data.user.json"

default_files = {
    user_data_path: {
        "statistics": {
            "users" : 0,
            "last_update": _datetimenow().timestamp()
        }
    }
}
if not log_dir.exists():
    os.makedirs(log_dir, exist_ok=True)

if not data_dir.exists():
    os.makedirs(data_dir, exist_ok=True)

if not user_data_path.exists():
    print(f"W: creating missing user data file: {user_data_path}")
    with open(user_data_path, 'w', encoding=ENCODING) as f:
        json.dump(default_files[user_data_path], f)

logger = logging.getLogger(name="logger")
log_formator = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# _log_fileHandler = logging.Handler(logging.DEBUG)
_log_fileHandler = ConcurrentTimedRotatingFileHandler(
    filename=log_file,
    when='w0',
    backupCount= 4 * 12, # about a year
    encoding=ENCODING,
    maxBytes= 1024* 1024* 2, # max to 2MB
    use_gzip=True,
)
_log_fileHandler.setFormatter(log_formator)

_log_consoleHandler = logging.Handler(logging.INFO)
_log_consoleHandler.setFormatter(log_formator)

logger.addHandler(_log_fileHandler)
logger.addHandler(_log_consoleHandler)

_log_level = os.environ.get("LOG_LEVEL")
if _log_level in {logging.DEBUG, logging.INFO, logging.WARNING}:
    logger.setLevel(_log_level)
else:
    logger.setLevel(logging.DEBUG)


db_conventions = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class DBBase(DeclarativeBase):
    metadata=MetaData(naming_convention=db_conventions)
    pass


db = SQLAlchemy(model_class=DBBase)

# set sqlite3 options
@event.listens_for(Engine, "connect")
def set_sqlite_pragmas(db_con, con_record):
    if not isinstance(db_con, SQLite3Connection):
        return

    cursor = db_con.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size = -16384") # 缓存 16MB
    cursor.execute("PRAGMA mmap_size = 134217728") # 内存映射 256MB
    cursor.execute("PRAGMA temp_store = MEMORY") # 临时表存储在内存
    cursor.execute("PRAGMA busy_timeout = 5000") # 锁等待超时 5 秒
    cursor.execute("PRAGMA journal_size_limit = 67108864") # set max wal size as 64MB
    cursor.close()

migrate = Migrate()
babel = Babel()

limiter = Limiter(
    get_remote_address,
    default_limits=["200 per day", "40 per minute"],
    storage_uri="memory://"
)

