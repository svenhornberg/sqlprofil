"""Schutz gegen schreibende oder mehrteilige SQL-Anweisungen.

Das ist die zweite Verteidigungslinie. Die erste ist ein Datenbankbenutzer, der nur lesen darf.
Ohne die erste ist die zweite nicht genug.
"""
from __future__ import annotations

import re

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|exec|execute|grant|revoke|deny|"
    r"backup|restore|shutdown|dbcc|bulk|openrowset|opendatasource|openquery|into|use|"
    r"sp_\w+|xp_\w+|waitfor|kill|reconfigure|"
    r"copy|call|do|vacuum|listen|notify|lock|set|reset|load|pg_\w+|lo_\w+|dblink\w*|"
    # DuckDB: kein Dateizugriff aus Abfragen heraus
    r"attach|detach|install|pragma|export|import|glob|getenv|read_\w+|\w+_scan|scan_\w+|query_table|query)\b",
    re.IGNORECASE,
)
_IDENT = re.compile(r"^[^\x00-\x1f\[\]\"]{1,128}$")


class UnsafeSql(ValueError):
    pass


def strip_comments_and_strings(sql: str) -> str:
    """Entfernt Kommentare und Literale, damit Schluesselwoerter in Texten nicht stoeren."""
    if re.search(r"\$\w*\$", sql):
        raise UnsafeSql("Dollar-Quoting ist nicht erlaubt.")
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"[NnEe]?'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r"\[(?:[^\]]|\]\])*\]", "[x]", sql)
    sql = re.sub(r'"(?:[^"]|"")*"', "[x]", sql)
    if re.search(r"\b(from|join)\s*''", sql, re.IGNORECASE):
        raise UnsafeSql("Dateien oder Texte als Tabelle sind nicht erlaubt.")
    return sql


def assert_readonly_select(sql: str) -> str:
    """Erlaubt genau eine SELECT- oder WITH-Anweisung."""
    cleaned = strip_comments_and_strings(sql).strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeSql("Leere Abfrage.")
    if ";" in cleaned:
        raise UnsafeSql("Nur eine einzelne Anweisung ist erlaubt.")
    if not re.match(r"^(select|with)\b", cleaned, re.IGNORECASE):
        raise UnsafeSql("Nur SELECT-Abfragen sind erlaubt.")
    hit = _FORBIDDEN.search(cleaned)
    if hit:
        raise UnsafeSql(f"Nicht erlaubtes Schluesselwort: {hit.group(0)}")
    return sql.strip().rstrip(";")


def assert_check_expression(expr: str) -> str:
    """Eine Regel ist ein boolescher Ausdruck fuer jede Zeile, keine ganze Abfrage."""
    if "--" in expr or "/*" in expr:
        raise UnsafeSql("Kommentare sind in Regeln nicht erlaubt.")
    cleaned = strip_comments_and_strings(expr).strip()
    if not cleaned:
        raise UnsafeSql("Leerer Regelausdruck.")
    if ";" in cleaned:
        raise UnsafeSql("Semikolon ist in Regeln nicht erlaubt.")
    hit = _FORBIDDEN.search(cleaned)
    if hit:
        raise UnsafeSql(f"Nicht erlaubtes Schluesselwort in Regel: {hit.group(0)}")
    depth = 0
    for ch in cleaned:
        depth += ch == "("
        depth -= ch == ")"
        if depth < 0:
            raise UnsafeSql("Klammern in der Regel sind nicht ausgeglichen.")
    if depth != 0:
        raise UnsafeSql("Klammern in der Regel sind nicht ausgeglichen.")
    return expr.strip()


def check_ident(name: str) -> str:
    if not _IDENT.match(name):
        raise UnsafeSql(f"Ungueltiger Bezeichner: {name!r}")
    return name


def split_table(table: str, default_schema: str) -> tuple[str, str]:
    """'dbo.Kunde' -> ('dbo', 'Kunde'); ohne Schema gilt das Standardschema des Dialekts."""
    parts = [p.strip().strip('[]"') for p in table.split(".")]
    if len(parts) == 1 and parts[0]:
        return default_schema, parts[0]
    if len(parts) == 2 and all(parts):
        return parts[0], parts[1]
    raise UnsafeSql(f"Tabelle bitte als schema.tabelle angeben: {table!r}")
