"""Die erzeugten Abfragen fuer SQL Server und PostgreSQL, ohne Datenbank geprueft."""
from sqlprofil import profiler, rules
from sqlprofil.dialects import get_dialect

COLS_MSSQL = [{"name": "id", "typ": "int"}, {"name": "name", "typ": "nvarchar"},
              {"name": "aktiv", "typ": "bit"}, {"name": "notiz", "typ": "ntext"}]
COLS_PG = [{"name": "id", "typ": "integer"}, {"name": "name", "typ": "character varying"},
           {"name": "aktiv", "typ": "boolean"}, {"name": "daten", "typ": "json"}]


def test_mssql_aggregate():
    d = get_dialect("mssql")
    sql = profiler.build_aggregate_sql(d, "dbo.Kunde", COLS_MSSQL, sample_percent=10)
    assert "COUNT_BIG(*) AS [zeilen]" in sql
    assert "APPROX_COUNT_DISTINCT([name])" in sql
    assert "MIN(LEN([name]))" in sql
    assert "SUM(CAST([aktiv] AS INT))" in sql
    assert "FROM [dbo].[Kunde] TABLESAMPLE (10 PERCENT)" in sql
    assert "DISTINCT([notiz])" not in sql and "[c3_leer]" in sql  # ntext: nur Leerwerte zaehlen


def test_mssql_top_und_regel():
    d = get_dialect("mssql")
    assert profiler.build_top_values_sql(d, "Kunde", "status").startswith("SELECT TOP 10 [status] AS [wert]")
    sql = rules.build_violation_sql(d, "Kunde", "ende >= beginn")
    assert sql == ("SELECT COUNT_BIG(*) AS [zeilen], SUM(CASE WHEN NOT (ende >= beginn) THEN 1 ELSE 0 END) "
                   "AS [verstoesse] FROM [dbo].[Kunde]")


def test_mssql_windows_auth():
    from sqlprofil.config import Settings
    from pathlib import Path
    s = Settings(dialect="mssql", dsn="", mssql_server="srv", mssql_database="db", mssql_trust_server_cert=True,
                 duckdb_init="", model="", api_base=None, api_key=None, max_rows=10, query_timeout=5,
                 chat_sql=False, chat_mode="patch", data_dir=Path("."))
    cs = get_dialect("mssql").connection_string(s)
    assert "Trusted_Connection=yes" in cs and "ApplicationIntent=ReadOnly" in cs
    assert "UID" not in cs and "PWD" not in cs


def test_postgres_aggregate():
    d = get_dialect("postgres")
    sql = profiler.build_aggregate_sql(d, "kunde", COLS_PG, sample_percent=5)
    assert 'COUNT(*) AS "zeilen"' in sql
    assert 'COUNT(DISTINCT "name")' in sql
    assert 'MIN(LENGTH("name"))' in sql
    assert 'SUM(CASE WHEN "aktiv" THEN 1 ELSE 0 END)' in sql
    assert 'FROM "public"."kunde" TABLESAMPLE SYSTEM (5)' in sql
    assert 'DISTINCT "daten"' not in sql
    assert profiler.build_top_values_sql(d, "kunde", "status").endswith("LIMIT 10")
    assert "%s" in profiler.columns_sql(d)
