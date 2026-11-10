import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_SQLITE_PATH = BACKEND_DIR / "predrive.db"


@dataclass(frozen=True)
class AppConfig:
    database_url: str
    jwt_secret: str
    jwt_algorithm: str
    jwt_expire_minutes: int
    heartbeat_retention_days: int
    watchdog_interval_sec: int
    enable_watchdog: bool


def get_config() -> AppConfig:
    default_db = f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"
    db_url = os.getenv("DATABASE_URL", default_db).strip()
    # Normalize postgres:// to postgresql:// if provided by cloud providers
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://") :]

    return AppConfig(
        database_url=db_url,
        jwt_secret=os.getenv(
            "PREDRIVE_JWT_SECRET",
            "predrive-m3-dev-secret-key-change-in-production-2026",
        ),
        jwt_algorithm=os.getenv("PREDRIVE_JWT_ALGORITHM", "HS256"),
        jwt_expire_minutes=int(os.getenv("PREDRIVE_JWT_EXPIRE_MINUTES", "1440")),
        heartbeat_retention_days=int(
            os.getenv("PREDRIVE_HEARTBEAT_RETENTION_DAYS", "7")
        ),
        watchdog_interval_sec=int(os.getenv("PREDRIVE_WATCHDOG_INTERVAL_SEC", "5")),
        enable_watchdog=os.getenv("PREDRIVE_ENABLE_WATCHDOG", "1") == "1",
    )

