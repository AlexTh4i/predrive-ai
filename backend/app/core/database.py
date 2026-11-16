from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_config


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
    url = database_url or get_config().database_url
    is_sqlite = url.startswith("sqlite")
    connect_args = {"check_same_thread": False, "timeout": 15} if is_sqlite else {}
    engine = create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        future=True,
    )
    if is_sqlite:
        event.listen(engine, "connect", _configure_sqlite_pragma)
    return engine


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


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

