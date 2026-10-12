"""Database helper. Works with SQLite (tests) and PostgreSQL (Docker / AWS RDS).

The database address comes from the DATABASE_URL environment variable.
"""
import os
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine, event


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (works the same in SQLite and Postgres)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def make_engine():
    url = os.getenv("DATABASE_URL", "sqlite:///./cloudpulse.db")
    if url.startswith("sqlite"):
        # Several local services share one file: wait for locks instead of failing, use WAL mode.
        eng = create_engine(url, connect_args={"timeout": 30, "check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _wal(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
        return eng
    return create_engine(url, pool_pre_ping=True)


def init_db(metadata, engine, retries: int = 40):
    """Create tables. Retries because the database container may still be starting."""
    for attempt in range(retries):
        try:
            metadata.create_all(engine)
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[db] not ready yet ({exc.__class__.__name__}), retry {attempt + 1}/{retries}")
            time.sleep(2)
    raise RuntimeError("Could not connect to the database. Check DATABASE_URL.")

