"""Konfiguration aus Umgebungsvariablen bzw. .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    dialect: str
    dsn: str
    mssql_server: str
    mssql_database: str
    mssql_trust_server_cert: bool
    duckdb_init: str
    model: str
    api_base: str | None
    api_key: str | None
    max_rows: int
    query_timeout: int
    chat_sql: bool
    chat_mode: str
    data_dir: Path

    @property
    def tables_dir(self) -> Path:
        return self.data_dir / "tables"

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


def demo_root() -> Path:
    return Path(os.getenv("SQLPROFIL_DEMO_DIR") or REPO_ROOT / "demo").resolve()


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "yes", "true", "ja", "on", "an"}


def get_settings() -> Settings:
    dialect = (os.getenv("SQLPROFIL_DIALECT") or "mssql").strip().lower()
    if dialect in {"postgresql", "pg"}:
        dialect = "postgres"
    if dialect in {"sqlserver", "sql server"}:
        dialect = "mssql"
    dsn = os.getenv("SQLPROFIL_DSN", "")
    data_dir = Path(os.getenv("SQLPROFIL_DATA_DIR") or REPO_ROOT / "daten").resolve()
    demo = (os.getenv("SQLPROFIL_DEMO") or "").strip().lower()
    if demo:  # Demo-Modus uebersteuert Datenbank und Datenverzeichnis
        dialect, dsn, data_dir = "duckdb", str(demo_root() / f"{demo}.duckdb"), demo_root() / demo
    return Settings(
        dialect=dialect,
        dsn=dsn,
        mssql_server=os.getenv("MSSQL_SERVER", ""),
        mssql_database=os.getenv("MSSQL_DATABASE", ""),
        mssql_trust_server_cert=_bool(os.getenv("MSSQL_TRUST_SERVER_CERT"), False),
        duckdb_init=os.getenv("SQLPROFIL_DUCKDB_INIT", ""),
        model=os.getenv("SQLPROFIL_MODEL", ""),
        api_base=os.getenv("SQLPROFIL_API_BASE") or None,
        api_key=os.getenv("SQLPROFIL_API_KEY") or None,
        max_rows=int(os.getenv("SQLPROFIL_MAX_ROWS", "100")),
        query_timeout=int(os.getenv("SQLPROFIL_QUERY_TIMEOUT", "60")),
        chat_sql=_bool(os.getenv("SQLPROFIL_CHAT_SQL"), False),
        chat_mode="direkt" if (os.getenv("SQLPROFIL_CHAT_MODE") or "patch").strip().lower() == "direkt" else "patch",
        data_dir=data_dir,
    )
