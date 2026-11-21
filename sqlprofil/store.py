"""Eine YAML-Datei pro Tabelle: Fachwissen, Spaltenerklaerungen, Regeln, offene Fragen.

Diese Dateien sind die einzige Quelle der Wahrheit und gehoeren ins Git.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any

import yaml

from sqlprofil.config import get_settings
from sqlprofil.dialects import get_dialect
from sqlprofil.sqlguard import assert_check_expression, split_table

RULE_STATUS = ("vorgeschlagen", "akzeptiert", "abgelehnt")


def _key(table: str) -> str:
    schema, name = split_table(table, get_dialect().default_schema)
    return f"{schema}.{name}"


def path_for(table: str) -> Path:
    safe = re.sub(r"[^\w.\-]", "_", _key(table))
    return get_settings().tables_dir / f"{safe}.yaml"


def _skeleton(table: str) -> dict[str, Any]:
    return {
        "tabelle": _key(table),
        "beschreibung": "",
        "owner": "",
        "steward": "",
        "spalten": {},
        "wissen": [],
        "regeln": [],
        "offene_fragen": [],
    }


def exists(table: str) -> bool:
    return path_for(table).exists()


def load(table: str) -> dict[str, Any]:
    p = path_for(table)
    doc = _skeleton(table)
    if p.exists():
        doc.update(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    for k, default in _skeleton(table).items():
        if doc.get(k) is None:
            doc[k] = default
    return doc


def save(doc: dict[str, Any]) -> Path:
    p = path_for(doc["tabelle"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
    return p


def list_tables() -> list[str]:
    d = get_settings().tables_dir
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


def ensure_columns(table: str, columns: list[str]) -> dict[str, Any]:
    """Legt fehlende Spalten an, ohne vorhandene Erklaerungen anzufassen."""
    doc = load(table)
    for col in columns:
        doc["spalten"].setdefault(col, {"bedeutung": "", "erlaubte_werte": [], "hinweise": "", "pii": False})
    save(doc)
    return doc


def document_column(table: str, column: str, bedeutung: str = "", hinweise: str = "",
                    erlaubte_werte: list[str] | None = None, pii: bool | None = None) -> dict[str, Any]:
    doc = load(table)
    entry = doc["spalten"].setdefault(column, {"bedeutung": "", "erlaubte_werte": [], "hinweise": "", "pii": False})
    if bedeutung:
        entry["bedeutung"] = bedeutung
    if hinweise:
        old = (entry.get("hinweise") or "").strip()
        entry["hinweise"] = f"{old}\n{hinweise}".strip() if old and hinweise not in old else hinweise
    if erlaubte_werte:
        entry["erlaubte_werte"] = list(erlaubte_werte)
    if pii is not None:
        entry["pii"] = bool(pii)
    save(doc)
    return entry


def add_knowledge(table: str, text: str, von: str = "") -> dict[str, Any]:
    doc = load(table)
    item = {"datum": _dt.date.today().isoformat(), "von": von, "text": text.strip()}
    doc["wissen"].append(item)
    save(doc)
    return item


def _norm(check: str) -> str:
    return re.sub(r"\s+", "", check).lower()


def add_rule(table: str, check: str, begruendung: str = "", status: str = "vorgeschlagen",
             quelle: str = "") -> tuple[dict[str, Any], bool]:
    """Fuegt eine Regel hinzu. Gibt (regel, neu) zurueck.

    Eine Regel mit gleichem Ausdruck wird nie doppelt angelegt. Das gilt auch fuer
    abgelehnte Regeln: so wird ein verworfener Vorschlag nicht bei jedem Lauf neu gemacht.
    """
    if status not in RULE_STATUS:
        raise ValueError(f"Status muss einer von {RULE_STATUS} sein.")
    check = assert_check_expression(check)
    doc = load(table)
    for rule in doc["regeln"]:
        if _norm(rule.get("check", "")) == _norm(check):
            return rule, False
    numbers = [int(m.group(1)) for r in doc["regeln"] if (m := re.fullmatch(r"r(\d+)", str(r.get("id", ""))))]
    rule = {
        "id": f"r{max(numbers, default=0) + 1}",
        "check": check,
        "status": status,
        "begruendung": begruendung.strip(),
        "quelle": quelle,
        "seit": _dt.date.today().isoformat(),
    }
    doc["regeln"].append(rule)
    save(doc)
    return rule, True


def set_rule_status(table: str, rule_id: str, status: str, begruendung: str = "") -> dict[str, Any]:
    if status not in RULE_STATUS:
        raise ValueError(f"Status muss einer von {RULE_STATUS} sein.")
    doc = load(table)
    for rule in doc["regeln"]:
        if rule.get("id") == rule_id:
            rule["status"] = status
            if begruendung:
                rule["begruendung"] = begruendung.strip()
            rule["entschieden"] = _dt.date.today().isoformat()
            save(doc)
            return rule
    raise KeyError(f"Regel {rule_id} gibt es in {table} nicht.")


def add_question(table: str, frage: str, spalte: str = "") -> tuple[dict[str, Any], bool]:
    doc = load(table)
    for q in doc["offene_fragen"]:
        if _norm(q.get("frage", "")) == _norm(frage):
            return q, False
    numbers = [int(m.group(1)) for q in doc["offene_fragen"] if (m := re.fullmatch(r"f(\d+)", str(q.get("id", ""))))]
    answered = [int(m.group(1)) for w in doc["wissen"] if (m := re.fullmatch(r"f(\d+)", str(w.get("frage_id", ""))))]
    q = {"id": f"f{max(numbers + answered, default=0) + 1}", "spalte": spalte, "frage": frage.strip()}
    doc["offene_fragen"].append(q)
    save(doc)
    return q, True


def answer_question(table: str, frage_id: str, antwort: str, von: str = "") -> dict[str, Any]:
    """Die Antwort wird zu dokumentiertem Wissen, die Frage verschwindet aus der offenen Liste."""
    doc = load(table)
    for q in list(doc["offene_fragen"]):
        if q.get("id") == frage_id:
            doc["offene_fragen"].remove(q)
            item = {
                "datum": _dt.date.today().isoformat(), "von": von, "frage_id": frage_id,
                "spalte": q.get("spalte", ""), "frage": q["frage"], "text": antwort.strip(),
            }
            doc["wissen"].append(item)
            save(doc)
            return item
    raise KeyError(f"Frage {frage_id} gibt es in {table} nicht.")
