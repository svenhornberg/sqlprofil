"""Lesbare Aenderungsvorschlaege fuer die Doku-Dateien ("Patch").

Ein Patch ist eine kurze YAML-Liste von Aktionen. Er entsteht im Chat, wird per Kopieren und
Einfuegen weitergegeben und von der Person, die das Repo pflegt, mit `sqlprofil patch` eingespielt.
Danach zeigt `git diff`, was sich an den Dateien geaendert hat.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any

import yaml

from sqlprofil import store
from sqlprofil.sqlguard import assert_check_expression

HEADER = "# sqlprofil-patch v1"

# aktion -> (Pflichtfelder, optionale Felder)
ACTIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "tabelle_beschreiben": (("tabelle",), ("beschreibung", "owner", "steward")),
    "spalte_dokumentieren": (("tabelle", "spalte"), ("bedeutung", "hinweise", "erlaubte_werte", "pii")),
    "wissen_festhalten": (("tabelle", "text"), ("von",)),
    "frage_beantworten": (("tabelle", "frage", "antwort"), ("von",)),
    "frage_stellen": (("tabelle", "frage"), ("spalte",)),
    "regel_vorschlagen": (("tabelle", "check"), ("begruendung",)),
    "regel_entscheiden": (("tabelle", "regel", "status"), ("begruendung",)),
}


class PatchError(ValueError):
    pass


def validate(op: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(op, dict):
        raise PatchError(f"Eintrag ist keine Aktion: {op!r}")
    action = op.get("aktion")
    if action not in ACTIONS:
        raise PatchError(f"Unbekannte Aktion {action!r}. Erlaubt: {', '.join(ACTIONS)}")
    required, optional = ACTIONS[action]
    missing = [f for f in required if op.get(f) in (None, "")]
    if missing:
        raise PatchError(f"{action}: es fehlt {', '.join(missing)}")
    unknown = set(op) - {"aktion", *required, *optional}
    if unknown:
        raise PatchError(f"{action}: unbekannte Felder {', '.join(sorted(unknown))}")
    if action == "regel_vorschlagen":
        assert_check_expression(str(op["check"]))
    if action == "regel_entscheiden" and op["status"] not in store.RULE_STATUS:
        raise PatchError(f"regel_entscheiden: Status muss einer von {store.RULE_STATUS} sein")
    return {k: v for k, v in op.items() if v not in (None, "", [])}


def describe(op: dict[str, Any]) -> str:
    """Ein Satz, den auch jemand ohne YAML-Kenntnis versteht."""
    a, t = op["aktion"], op["tabelle"]
    if a == "tabelle_beschreiben":
        parts = [f"{k} = {op[k]!r}" for k in ("beschreibung", "owner", "steward") if op.get(k)]
        return f"{t}: " + ", ".join(parts)
    if a == "spalte_dokumentieren":
        parts = [f"{k}: {op[k]}" for k in ("bedeutung", "hinweise", "erlaubte_werte", "pii") if k in op]
        return f"{t}.{op['spalte']} dokumentieren ({'; '.join(parts)})"
    if a == "wissen_festhalten":
        return f"{t}: Wissen festhalten: {op['text']}"
    if a == "frage_beantworten":
        return f"{t}: Frage {op['frage']} beantworten: {op['antwort']}"
    if a == "frage_stellen":
        return f"{t}: neue offene Frage: {op['frage']}"
    if a == "regel_vorschlagen":
        return f"{t}: Regel vorschlagen: {op['check']}"
    return f"{t}: Regel {op['regel']} auf {op['status']} setzen" + (
        f" ({op['begruendung']})" if op.get("begruendung") else "")


def _find_rule_id(table: str, ref: str) -> str:
    """Eine Regel wird ueber ihre ID (r3) oder ueber ihren Ausdruck angesprochen."""
    doc = store.load(table)
    norm = re.sub(r"\s+", "", str(ref)).lower()
    for rule in doc["regeln"]:
        if rule.get("id") == ref or re.sub(r"\s+", "", rule.get("check", "")).lower() == norm:
            return rule["id"]
    raise PatchError(f"Regel {ref!r} gibt es in {table} nicht.")


def _find_question_id(table: str, ref: str) -> str:
    doc = store.load(table)
    norm = re.sub(r"\s+", "", str(ref)).lower()
    for q in doc["offene_fragen"]:
        if q.get("id") == ref or re.sub(r"\s+", "", q.get("frage", "")).lower() == norm:
            return q["id"]
    raise PatchError(f"Offene Frage {ref!r} gibt es in {table} nicht.")


def apply_op(op: dict[str, Any]) -> None:
    op = validate(op)
    a, t = op["aktion"], op["tabelle"]
    if a == "tabelle_beschreiben":
        doc = store.load(t)
        for k in ("beschreibung", "owner", "steward"):
            if op.get(k):
                doc[k] = op[k]
        store.save(doc)
    elif a == "spalte_dokumentieren":
        store.document_column(t, op["spalte"], op.get("bedeutung", ""), op.get("hinweise", ""),
                              op.get("erlaubte_werte"), op.get("pii"))
    elif a == "wissen_festhalten":
        store.add_knowledge(t, op["text"], op.get("von", ""))
    elif a == "frage_beantworten":
        store.answer_question(t, _find_question_id(t, op["frage"]), op["antwort"], op.get("von", ""))
    elif a == "frage_stellen":
        store.add_question(t, op["frage"], op.get("spalte", ""))
    elif a == "regel_vorschlagen":
        store.add_rule(t, op["check"], op.get("begruendung", ""), "vorgeschlagen", "patch")
    elif a == "regel_entscheiden":
        store.set_rule_status(t, _find_rule_id(t, op["regel"]), op["status"], op.get("begruendung", ""))


def apply_ops(ops: list[dict[str, Any]], dry_run: bool = False) -> list[str]:
    """Spielt alle Aktionen ein. Erst wird alles geprueft, damit kein halber Patch entsteht."""
    checked = [validate(op) for op in ops]
    lines = []
    for op in checked:
        if op["aktion"] == "regel_entscheiden":
            # Regeln, die derselbe Patch erst vorschlaegt, gibt es beim Pruefen noch nicht
            proposed_here = any(o["aktion"] == "regel_vorschlagen" and o["tabelle"] == op["tabelle"]
                                and re.sub(r"\s+", "", o["check"]).lower() == re.sub(r"\s+", "", str(op["regel"])).lower()
                                for o in checked)
            if not proposed_here:
                _find_rule_id(op["tabelle"], op["regel"])
        if op["aktion"] == "frage_beantworten":
            _find_question_id(op["tabelle"], op["frage"])
        lines.append(describe(op))
    if not dry_run:
        for op in checked:
            apply_op(op)
    return lines


def render(ops: list[dict[str, Any]], von: str = "") -> str:
    checked = [validate(op) for op in ops]
    head = [HEADER, f"# Datum: {_dt.date.today().isoformat()}" + (f", von: {von}" if von else ""),
            "# Einspielen: sqlprofil patch <datei>   (vorher pruefen: --dry-run)", "#",
            "# Was sich aendert:"]
    head += [f"#  {i}. {describe(op)}" for i, op in enumerate(checked, 1)]
    body = yaml.safe_dump(checked, sort_keys=False, allow_unicode=True, width=100, default_flow_style=False)
    return "\n".join(head) + "\n\n" + body


def parse(text: str) -> list[dict[str, Any]]:
    """Vertraegt eingefuegten Text aus Chat oder Mail: Code-Zaeune und Text davor werden ignoriert."""
    text = text.replace("\r\n", "\n").replace(" ", " ")
    m = re.search(r"```(?:yaml|yml)?\n(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    if HEADER in text:
        text = text[text.index(HEADER):]
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PatchError(f"Patch ist kein gueltiges YAML: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, list):
        raise PatchError("Ein Patch ist eine Liste von Aktionen (jede beginnt mit '- aktion: ...').")
    return [validate(op) for op in data]
