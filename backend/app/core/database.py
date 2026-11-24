from collections.abc import Generator
import os
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from .config import get_config, normalize_database_url


class Base(DeclarativeBase):
    pass


def _configure_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


def build_engine(database_url: str | None = None) -> Engine:
    raw_url = database_url or get_config().database_url
    url = normalize_database_url(raw_url)
    is_sqlite = url.startswith("sqlite")

    if is_sqlite:
        connect_args: dict[str, Any] = {"check_same_thread": False, "timeout": 15}
        engine = create_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
            future=True,
        )
        event.listen(engine, "connect", _configure_sqlite_pragma)
        return engine

    # PostgreSQL / Supabase configuration (Session or Transaction Pooler safe)
    is_tx_pooler = (
        ":6543" in url
        or "pooler.supabase.com" in url
        or os.getenv("PREDRIVE_DB_USE_NULLPOOL", "0") == "1"
    )
    pg_connect_args: dict[str, Any] = {}
    if is_tx_pooler:
        # Disable psycopg3 server-side prepared statements when behind PgBouncer/Supavisor
        pg_connect_args["prepare_threshold"] = None

    use_nullpool = ":6543" in url or os.getenv("PREDRIVE_DB_USE_NULLPOOL", "0") == "1"
    if use_nullpool:
        return create_engine(
            url,
            connect_args=pg_connect_args,
            poolclass=NullPool,
            future=True,
        )

    pool_size = max(1, int(os.getenv("PREDRIVE_DB_POOL_SIZE", "5")))
    max_overflow = max(0, int(os.getenv("PREDRIVE_DB_MAX_OVERFLOW", "10")))
    pool_recycle = max(30, int(os.getenv("PREDRIVE_DB_POOL_RECYCLE", "300")))

    return create_engine(
        url,
        connect_args=pg_connect_args,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        pool_timeout=30,
        future=True,
    )


engine = build_engine()
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def reset_engine(database_url: str) -> Engine:
    """Rebind global engine and SessionLocal (useful for isolated tests)."""
    global engine
    engine.dispose()
    engine = build_engine(database_url)
    SessionLocal.configure(bind=engine)
    return engine


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
