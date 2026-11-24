import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_SQLITE_PATH = BACKEND_DIR / "predrive.db"
ENV_FILE_PATH = BACKEND_DIR / ".env"


def _load_backend_dotenv() -> None:
    """Load key=value pairs from backend/.env into os.environ if not already set."""
    if not ENV_FILE_PATH.exists():
        return
    for raw_line in ENV_FILE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        if key and key not in os.environ and "<YOUR_DB_PASSWORD>" not in val:
            os.environ[key] = val


_load_backend_dotenv()


def normalize_database_url(raw_url: str) -> str:
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]

    # Safely URL-encode unescaped special characters (like '@') in password and strip placeholder '<...>'
    if "://" in url and "@" in url:
        scheme, rest = url.split("://", 1)
        path_idx = rest.find("/")
        authority = rest[:path_idx] if path_idx != -1 else rest
        tail = rest[path_idx:] if path_idx != -1 else ""
        if "@" in authority:
            userinfo, hostport = authority.rsplit("@", 1)
            if ":" in userinfo:
                user, raw_pwd = userinfo.split(":", 1)
                if raw_pwd.startswith("<") and raw_pwd.endswith(">") and len(raw_pwd) > 2:
                    raw_pwd = raw_pwd[1:-1]
                enc_pwd = quote(unquote(raw_pwd), safe="")
                url = f"{scheme}://{user}:{enc_pwd}@{hostport}{tail}"

    # Auto-enforce sslmode=require for Supabase cloud hosts (direct or pooler) if not explicitly set
    if url.startswith("postgresql") and (
        "supabase.co" in url or "supabase.com" in url
    ):
        parts = urlsplit(url)
        q = dict(parse_qsl(parts.query, keep_blank_values=True))
        if "sslmode" not in q:
            q["sslmode"] = "require"
        if ":6543" in parts.netloc:
            q.pop("pgbouncer", None)
        url = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment)
        )
    return url


@dataclass(frozen=True)
class AppConfig:
    env: str
    database_url: str
    jwt_secret: str
    jwt_algorithm: str
    jwt_expire_minutes: int
    refresh_token_expire_days: int
    heartbeat_retention_days: int
    watchdog_interval_sec: int
    enable_watchdog: bool
    cors_origins: list[str]
    redis_url: str | None
    sentry_dsn: str | None
    max_body_bytes: int

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def get_config() -> AppConfig:
    env = os.getenv("ENV", os.getenv("PREDRIVE_ENV", "development")).strip().lower()
    default_db = f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"
    raw_db_url = os.getenv("DATABASE_URL", default_db)
    db_url = normalize_database_url(raw_db_url)

    default_expire = "15" if env == "production" else "15"
    raw_cors = os.getenv(
        "CORS_ORIGINS",
        os.getenv(
            "PREDRIVE_ALLOWED_ORIGINS",
            ""
            if env == "production"
            else (
                "http://localhost:5173,https://localhost:5173,http://127.0.0.1:5173,"
                "http://localhost:5174,http://127.0.0.1:5174,http://localhost:4174,"
                "http://127.0.0.1:4174,https://localhost,http://localhost,capacitor://localhost"
            ),
        ),
    )
    cors_origins = [o.strip() for o in raw_cors.split(",") if o.strip()]

    redis_url = os.getenv("REDIS_URL", "").strip() or None
    sentry_dsn = os.getenv("SENTRY_DSN", "").strip() or None

    return AppConfig(
        env=env,
        database_url=db_url,
        jwt_secret=os.getenv(
            "PREDRIVE_JWT_SECRET",
            "predrive-m3-dev-secret-key-change-in-production-2026",
        ),
        jwt_algorithm=os.getenv("PREDRIVE_JWT_ALGORITHM", "HS256"),
        jwt_expire_minutes=int(os.getenv("PREDRIVE_JWT_EXPIRE_MINUTES", default_expire)),
        refresh_token_expire_days=int(
            os.getenv("PREDRIVE_REFRESH_EXPIRE_DAYS", "30")
        ),
        heartbeat_retention_days=int(
            os.getenv("PREDRIVE_HEARTBEAT_RETENTION_DAYS", "30")
        ),
        watchdog_interval_sec=int(os.getenv("PREDRIVE_WATCHDOG_INTERVAL_SEC", "5")),
        enable_watchdog=os.getenv("PREDRIVE_ENABLE_WATCHDOG", "1") == "1",
        cors_origins=cors_origins,
        redis_url=redis_url,
        sentry_dsn=sentry_dsn,
        max_body_bytes=int(os.getenv("PREDRIVE_MAX_BODY_BYTES", str(2 * 1024 * 1024))),
    )
