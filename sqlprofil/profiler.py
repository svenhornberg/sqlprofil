"""Profiling ohne KI: reine Kennzahlen pro Spalte, ein Tabellenscan fuer die Aggregate."""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any

from sqlprofil import store
from sqlprofil.config import get_settings
from sqlprofil.dialects import Dialect, fetch, get_dialect
from sqlprofil.sqlguard import split_table

# Spaltennamen, bei denen keine Einzelwerte ins Profil (und damit ans Modell) gehen
PII_NAME = re.compile(
    r"(name|vorname|nachname|mail|telefon|phone|mobil|fax|strasse|straße|street|adresse|address|plz|zip|"
    r"iban|bic|konto|account|geburt|birth|steuer|tax|ausweis|passwort|password|kennwort)",
    re.IGNORECASE,
)
TOP_VALUES_MAX_DISTINCT = 50
TOP_N = 10


def is_pii(column: str, doc_entry: dict[str, Any] | None) -> bool:
    if doc_entry and doc_entry.get("pii") is True:
        return True
    if doc_entry and doc_entry.get("pii") == "nein":  # bewusst freigegeben, z. B. "produktname"
        return False
    return bool(PII_NAME.search(column))


def build_aggregate_sql(d: Dialect, table: str, columns: list[dict[str, Any]],
                        sample_percent: float | None = None) -> str:
    """Eine einzige Abfrage mit allen Spaltenkennzahlen. Aliasse: c<i>_<kennzahl>."""
    a = d.quote
    exprs = [f"{d.count_all} AS {a('zeilen')}"]
    for i, col in enumerate(columns):
        q = d.quote(col["name"])
        t = col["typ"]

        def add(expr: str, key: str) -> None:
            exprs.append(f"{expr} AS {a(f'c{i}_{key}')}")

        add(f"SUM(CASE WHEN {q} IS NULL THEN 1 ELSE 0 END)", "leer")
        if t in d.opaque_types:
            continue
        add(d.distinct(q), "verschiedene")
        if t in d.string_types:
            add(f"SUM(CASE WHEN {q} = '' THEN 1 ELSE 0 END)", "leerstring")
            add(f"SUM(CASE WHEN {q} LIKE ' %' OR {q} LIKE '% ' THEN 1 ELSE 0 END)", "randleerzeichen")
            add(f"MIN({d.length(q)})", "min_laenge")
            add(f"MAX({d.length(q)})", "max_laenge")
        elif t in d.numeric_types or t in d.date_types:
            add(f"MIN({q})", "min")
            add(f"MAX({q})", "max")
            if t in d.numeric_types:
                add(f"SUM(CASE WHEN {q} = 0 THEN 1 ELSE 0 END)", "null_wert")
                add(f"SUM(CASE WHEN {q} < 0 THEN 1 ELSE 0 END)", "negativ")
        elif t in d.bool_types:
            add(d.bool_true(q), "wahr")
    return "SELECT\n  " + ",\n  ".join(exprs) + f"\nFROM {d.qualified(table)}{d.sample(sample_percent)}"


def build_top_values_sql(d: Dialect, table: str, column: str, sample_percent: float | None = None) -> str:
    q = d.quote(column)
    rest = (f"FROM {d.qualified(table)}{d.sample(sample_percent)} "
            f"GROUP BY {q} ORDER BY {d.count_all} DESC, {q}")
    return d.top(f"{q} AS {d.quote('wert')}, {d.count_all} AS {d.quote('anzahl')}", rest, TOP_N)


def columns_sql(d: Dialect) -> str:
    return (
        "SELECT c.COLUMN_NAME, c.DATA_TYPE, c.CHARACTER_MAXIMUM_LENGTH, c.IS_NULLABLE "
        "FROM INFORMATION_SCHEMA.COLUMNS c "
        f"WHERE c.TABLE_SCHEMA = {d.placeholder} AND c.TABLE_NAME = {d.placeholder} "
        "ORDER BY c.ORDINAL_POSITION"
    )


def keys_sql(d: Dialect) -> str:
    return (
        "SELECT kcu.COLUMN_NAME, tc.CONSTRAINT_TYPE "
        "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc "
        "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu "
        "  ON kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME AND kcu.TABLE_SCHEMA = tc.TABLE_SCHEMA "
        " AND kcu.TABLE_NAME = tc.TABLE_NAME "
        f"WHERE tc.TABLE_SCHEMA = {d.placeholder} AND tc.TABLE_NAME = {d.placeholder} "
        "  AND tc.CONSTRAINT_TYPE IN ('PRIMARY KEY', 'FOREIGN KEY', 'UNIQUE')"
    )


TABLES_SQL = ("SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
              "ORDER BY TABLE_SCHEMA, TABLE_NAME")


def list_db_tables(include_views: bool = True) -> list[tuple[str, bool]]:
    """Alle Tabellen der Datenbank als (schema.tabelle, ist_view)."""
    d = get_dialect()
    with d.connect() as conn:
        _, rows = fetch(conn, TABLES_SQL)
    out = [(f"{r[0]}.{r[1]}", str(r[2]).upper() == "VIEW") for r in rows if r[0] not in d.system_schemas]
    return [t for t in out if include_views or not t[1]]


def read_columns(d: Dialect, conn: Any, table: str) -> list[dict[str, Any]]:
    schema, name = split_table(table, d.default_schema)
    _, rows = fetch(conn, columns_sql(d), (schema, name))
    if not rows:
        raise LookupError(f"Tabelle {schema}.{name} nicht gefunden oder keine Leserechte.")
    _, keys = fetch(conn, keys_sql(d), (schema, name))
    key_map: dict[str, list[str]] = {}
    for col, kind in keys:
        key_map.setdefault(col, []).append(kind)
    return [
        {"name": r[0], "typ": d.normalize_type(r[1]), "max_laenge": r[2], "nullable": r[3] == "YES",
         "schluessel": sorted(set(key_map.get(r[0], [])))}
        for r in rows
    ]


def profile_path(table: str) -> Path:
    return get_settings().profiles_dir / (store.path_for(table).stem + ".json")


def load_profile(table: str) -> dict[str, Any] | None:
    p = profile_path(table)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def profile_table(table: str, sample_percent: float | None = None) -> dict[str, Any]:
    d = get_dialect()
    with d.connect() as conn:
        columns = read_columns(d, conn, table)
        doc = store.ensure_columns(table, [c["name"] for c in columns])
        names, rows = fetch(conn, build_aggregate_sql(d, table, columns, sample_percent))
        agg = dict(zip(names, rows[0])) if rows else {}
        total = int(agg.get("zeilen") or 0)

        result_cols = []
        for i, col in enumerate(columns):
            stats = {k[len(f"c{i}_"):]: v for k, v in agg.items() if k.startswith(f"c{i}_")}
            leer = int(stats.get("leer") or 0)
            if stats.get("verschiedene") is not None:
                # Geschaetzte Werte (SQL Server) koennen leicht ueber der Zeilenzahl liegen
                stats["verschiedene"] = min(int(stats["verschiedene"]), total - leer)
            entry: dict[str, Any] = {**col, **stats, "leer": leer,
                                     "leer_anteil": round(leer / total, 4) if total else None}
            pii = is_pii(col["name"], doc["spalten"].get(col["name"]))
            entry["pii"] = pii
            distinct = stats.get("verschiedene")
            categorical = distinct is not None and int(distinct) <= TOP_VALUES_MAX_DISTINCT
            all_unique = int(distinct or 0) == total - leer and total > TOP_N  # z. B. Schluessel
            if not pii and categorical and total and not all_unique:
                _, top = fetch(conn, build_top_values_sql(d, table, col["name"], sample_percent))
                entry["haeufigste_werte"] = [{"wert": w, "anzahl": int(n)} for w, n in top]
            result_cols.append(entry)

    profile = {
        "tabelle": doc["tabelle"],
        "dialekt": d.name,
        "verschiedene_geschaetzt": d.distinct_is_approx,
        "erstellt": _dt.datetime.now().isoformat(timespec="seconds"),
        "stichprobe_prozent": sample_percent,
        "zeilen": total,
        "spalten": result_cols,
    }
    p = profile_path(table)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile
