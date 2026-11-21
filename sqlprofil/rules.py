"""Regeln ausfuehren. Eine Regel ist ein Ausdruck, der fuer jede Zeile wahr sein soll."""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

from sqlprofil import store
from sqlprofil.config import get_settings
from sqlprofil.dialects import Dialect, fetch, get_dialect
from sqlprofil.sqlguard import assert_check_expression


def build_violation_sql(d: Dialect, table: str, check: str) -> str:
    """Zaehlt Zeilen, die die Regel verletzen.

    Achtung SQL-Logik: ergibt der Ausdruck NULL (z. B. Vergleich mit leerem Wert), zaehlt die
    Zeile nicht als Verstoss. Wer Leerwerte verbieten will, schreibt das ausdruecklich:
    "ende IS NOT NULL AND ende >= beginn".
    """
    check = assert_check_expression(check)
    return (f"SELECT {d.count_all} AS {d.quote('zeilen')}, "
            f"SUM(CASE WHEN NOT ({check}) THEN 1 ELSE 0 END) AS {d.quote('verstoesse')} "
            f"FROM {d.qualified(table)}")


def test_rule(table: str, check: str, conn: Any | None = None) -> dict[str, Any]:
    d = get_dialect()
    sql = build_violation_sql(d, table, check)
    if conn is None:
        with d.connect() as c:
            _, rows = fetch(c, sql)
    else:
        _, rows = fetch(conn, sql)
    total = int(rows[0][0] or 0)
    bad = int(rows[0][1] or 0)
    return {"check": check, "zeilen": total, "verstoesse": bad,
            "anteil": round(bad / total, 4) if total else None}


test_rule.__test__ = False  # kein pytest-Test, auch wenn der Name so aussieht


def results_path(table: str) -> Path:
    return get_settings().profiles_dir / (store.path_for(table).stem + ".checks.json")


def load_results(table: str) -> dict[str, Any] | None:
    p = results_path(table)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def run_rules(table: str, statuses: tuple[str, ...] = ("akzeptiert",)) -> dict[str, Any]:
    d = get_dialect()
    doc = store.load(table)
    out = []
    with d.connect() as conn:
        for rule in doc["regeln"]:
            if rule.get("status") not in statuses:
                continue
            try:
                res = test_rule(table, rule["check"], conn)
                out.append({"id": rule["id"], "status": rule["status"], **res})
            except Exception as exc:  # eine kaputte Regel soll die anderen nicht aufhalten
                out.append({"id": rule["id"], "status": rule["status"], "check": rule["check"], "fehler": str(exc)})
    result = {"tabelle": doc["tabelle"], "erstellt": _dt.datetime.now().isoformat(timespec="seconds"), "regeln": out}
    p = results_path(table)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
