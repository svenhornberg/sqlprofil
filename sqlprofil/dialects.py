"""Alles, was sich zwischen SQL Server und PostgreSQL unterscheidet."""
from __future__ import annotations

import datetime as _dt
import decimal
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from sqlprofil.config import Settings, get_settings
from sqlprofil.sqlguard import check_ident, split_table


class Dialect:
    name = ""
    default_schema = ""
    placeholder = "?"
    count_all = "COUNT(*)"
    distinct_is_approx = False
    string_types: set[str] = set()
    numeric_types: set[str] = set()
    date_types: set[str] = set()
    bool_types: set[str] = set()
    # Typen, auf denen weder DISTINCT noch MIN/MAX erlaubt oder sinnvoll sind
    opaque_types: set[str] = set()
    system_schemas: tuple[str, ...] = ()

    def quote(self, ident: str) -> str:
        raise NotImplementedError

    def normalize_type(self, data_type: str) -> str:
        return str(data_type).lower()

    def qualified(self, table: str) -> str:
        schema, name = split_table(table, self.default_schema)
        return f"{self.quote(schema)}.{self.quote(name)}"

    def distinct(self, q: str) -> str:
        return f"COUNT(DISTINCT {q})"

    def length(self, q: str) -> str:
        return f"LENGTH({q})"

    def bool_true(self, q: str) -> str:
        return f"SUM(CASE WHEN {q} THEN 1 ELSE 0 END)"

    def sample(self, percent: float | None) -> str:
        return ""

    def top(self, select_list: str, rest: str, n: int) -> str:
        return f"SELECT {select_list} {rest} LIMIT {int(n)}"

    def connection_string(self, settings: Settings) -> str:
        raise NotImplementedError

    @contextmanager
    def connect(self, settings: Settings | None = None) -> Iterator[Any]:
        raise NotImplementedError
        yield


class MsSql(Dialect):
    name = "mssql"
    default_schema = "dbo"
    placeholder = "?"
    count_all = "COUNT_BIG(*)"
    distinct_is_approx = True
    string_types = {"char", "varchar", "nchar", "nvarchar"}
    numeric_types = {"tinyint", "smallint", "int", "bigint", "decimal", "numeric", "money", "smallmoney",
                     "float", "real"}
    date_types = {"date", "datetime", "datetime2", "smalldatetime", "datetimeoffset", "time"}
    bool_types = {"bit"}
    opaque_types = {"text", "ntext", "image", "xml", "geography", "geometry", "hierarchyid", "sql_variant",
                    "timestamp", "rowversion", "varbinary", "binary"}
    system_schemas = ("sys", "INFORMATION_SCHEMA")

    def quote(self, ident: str) -> str:
        return "[" + check_ident(ident) + "]"

    def distinct(self, q: str) -> str:
        return f"APPROX_COUNT_DISTINCT({q})"  # ab SQL Server 2019, deutlich billiger als COUNT(DISTINCT)

    def length(self, q: str) -> str:
        return f"LEN({q})"

    def bool_true(self, q: str) -> str:
        return f"SUM(CAST({q} AS INT))"

    def sample(self, percent: float | None) -> str:
        return f" TABLESAMPLE ({float(percent):g} PERCENT)" if percent else ""

    def top(self, select_list: str, rest: str, n: int) -> str:
        return f"SELECT TOP {int(n)} {select_list} {rest}"

    def connection_string(self, settings: Settings) -> str:
        if settings.dsn:
            return settings.dsn
        if not settings.mssql_server or not settings.mssql_database:
            raise RuntimeError("MSSQL_SERVER und MSSQL_DATABASE muessen gesetzt sein (siehe .env.example).")
        return ";".join([
            f"Server={settings.mssql_server}",
            f"Database={settings.mssql_database}",
            "Trusted_Connection=yes",  # Windows-Authentifizierung des angemeldeten Benutzers
            "Encrypt=yes",
            f"TrustServerCertificate={'yes' if settings.mssql_trust_server_cert else 'no'}",
            "ApplicationIntent=ReadOnly",  # landet bei Always On auf der lesbaren Replika
        ])

    @contextmanager
    def connect(self, settings: Settings | None = None) -> Iterator[Any]:
        try:
            import mssql_python
        except ImportError as exc:
            raise RuntimeError('Treiber fehlt: pip install -e ".[mssql]"') from exc
        settings = settings or get_settings()
        conn = mssql_python.connect(self.connection_string(settings), autocommit=True)
        try:
            conn.timeout = settings.query_timeout
            yield conn
        finally:
            conn.close()


class Postgres(Dialect):
    name = "postgres"
    default_schema = "public"
    placeholder = "%s"
    string_types = {"character varying", "character", "text", "citext"}
    numeric_types = {"smallint", "integer", "bigint", "numeric", "real", "double precision"}
    date_types = {"date", "timestamp without time zone", "timestamp with time zone",
                  "time without time zone", "time with time zone"}
    bool_types = {"boolean"}
    opaque_types = {"json", "xml", "bytea", "point", "line", "lseg", "box", "path", "polygon", "circle",
                    "array", "tsvector", "tsquery"}
    system_schemas = ("pg_catalog", "information_schema")

    def quote(self, ident: str) -> str:
        return '"' + check_ident(ident) + '"'

    def sample(self, percent: float | None) -> str:
        return f" TABLESAMPLE SYSTEM ({float(percent):g})" if percent else ""

    def connection_string(self, settings: Settings) -> str:
        return settings.dsn  # leer = libpq liest PGHOST, PGDATABASE, PGUSER, pgpass usw.

    @contextmanager
    def connect(self, settings: Settings | None = None) -> Iterator[Any]:
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError('Treiber fehlt: pip install -e ".[postgres]"') from exc
        settings = settings or get_settings()
        # Die Sitzung ist auf Datenbankebene schreibgeschuetzt, unabhaengig vom SQL-Filter.
        options = f"-c default_transaction_read_only=on -c statement_timeout={settings.query_timeout * 1000}"
        conn = psycopg.connect(self.connection_string(settings), autocommit=True, options=options)
        try:
            yield conn
        finally:
            conn.close()


class DuckDb(Dialect):
    """DuckDB als eigene Datenbank oder als Huelle um Parquet, CSV, SQLite und andere Quellen."""

    name = "duckdb"
    default_schema = "main"
    placeholder = "?"
    string_types = {"varchar"}
    numeric_types = {"tinyint", "smallint", "integer", "bigint", "hugeint", "utinyint", "usmallint", "uinteger",
                     "ubigint", "uhugeint", "float", "double", "decimal"}
    date_types = {"date", "time", "timestamp", "timestamp with time zone", "timestamp_s", "timestamp_ms",
                  "timestamp_ns", "time with time zone"}
    bool_types = {"boolean"}
    opaque_types = {"blob", "list", "struct", "map", "union", "json", "bit", "interval"}
    system_schemas = ("information_schema", "pg_catalog")

    def quote(self, ident: str) -> str:
        return '"' + check_ident(ident) + '"'

    def normalize_type(self, data_type: str) -> str:
        t = str(data_type).lower()
        if t.endswith("]"):
            return "list"
        for prefix in ("struct", "map", "union"):
            if t.startswith(prefix):
                return prefix
        return t.split("(")[0].strip()  # decimal(10,2) -> decimal

    def sample(self, percent: float | None) -> str:
        return f" USING SAMPLE {float(percent):g} PERCENT (system)" if percent else ""

    def connection_string(self, settings: Settings) -> str:
        return settings.dsn or ":memory:"

    @contextmanager
    def connect(self, settings: Settings | None = None) -> Iterator[Any]:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError('Treiber fehlt: pip install -e ".[duckdb]"') from exc
        settings = settings or get_settings()
        path = self.connection_string(settings)
        in_memory = path == ":memory:"
        conn = duckdb.connect(path, read_only=not in_memory)
        try:
            if settings.duckdb_init:
                # Vom Betreiber gepflegtes Skript, z. B. CREATE VIEW ... AS SELECT * FROM read_parquet(...).
                # Nur sinnvoll mit :memory:, eine Datei wird schreibgeschuetzt geoeffnet.
                conn.execute(Path(settings.duckdb_init).read_text(encoding="utf-8"))
            conn.execute("SET lock_configuration = true")
            yield conn
        finally:
            conn.close()


_DIALECTS = {"mssql": MsSql, "postgres": Postgres, "duckdb": DuckDb}


def get_dialect(name: str | None = None) -> Dialect:
    name = name or get_settings().dialect
    try:
        return _DIALECTS[name]()
    except KeyError:
        raise RuntimeError(f"Unbekannter Dialekt {name!r}. Erlaubt: mssql, postgres, duckdb.") from None


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} Bytes>"
    return str(value)


def fetch(conn: Any, sql: str, params: tuple = (), max_rows: int | None = None) -> tuple[list[str], list[list[Any]]]:
    cur = conn.cursor()
    try:
        cur.execute(sql, params) if params else cur.execute(sql)
        columns = [d[0] for d in (cur.description or [])]
        rows = cur.fetchmany(max_rows) if max_rows else cur.fetchall()
        return columns, [[jsonable(v) for v in row] for row in rows]
    finally:
        cur.close()
