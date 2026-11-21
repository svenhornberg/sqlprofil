"""Report pro Tabelle: Fakten kommen aus dem Profil, Einschaetzung und Vorschlaege vom Modell.

Zahlen im Faktenteil rechnet der Code, nie das Modell. Das Modell sieht nur Kennzahlen,
die Doku-Datei und Regelergebnisse, keine Rohzeilen.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any

from sqlprofil import profiler, rules, store
from sqlprofil.config import get_settings
from sqlprofil.sqlguard import UnsafeSql, assert_check_expression

SYSTEM_PROMPT = """Du bist Analyst fuer Datenqualitaet. Du bekommst zu genau einer Tabelle:
Kennzahlen pro Spalte (Profil), die gepflegte Dokumentation mit Fachwissen und Regeln, und Ergebnisse
der akzeptierten Regeln.

Antworte ausschliesslich mit einem JSON-Objekt mit diesen Schluesseln:
- "einschaetzung": Markdown, hoechstens 12 Saetze oder Stichpunkte. Die wichtigsten Auffaelligkeiten
  zuerst, jeweils mit der Zahl aus dem Profil. Keine Zahlen erfinden. Was laut Dokumentation
  beabsichtigt ist, ist keine Auffaelligkeit.
- "regelvorschlaege": Liste von {"check": ..., "begruendung": ...}. "check" ist ein boolescher
  SQL-Ausdruck im Dialekt %(dialekt)s, der fuer jede einzelne Zeile wahr sein soll. Nur Spalten
  dieser Tabelle, keine Unterabfragen, keine Semikolons, keine Kommentare. Spaltennamen so
  quotieren wie im Dialekt ueblich, wenn sie Sonderzeichen enthalten.
  Schlage nichts vor, was schon in der Dokumentation unter "regeln" steht. Das gilt besonders fuer
  abgelehnte Regeln: deren Begruendung ist Fachwissen. Hoechstens 8 Vorschlaege, die wertvollsten zuerst.
- "fragen": Liste von {"spalte": ..., "frage": ...}. Konkrete Fragen an die Fachabteilung, die nur
  ein Mensch beantworten kann (z. B. "12 %% der Zeilen haben kein Enddatum. Ist das bei laufenden
  Vertraegen so gewollt?"). Nichts fragen, was die Dokumentation schon beantwortet. Hoechstens 8.
"""


def _pct(x: Any) -> str:
    return "" if x is None else f"{float(x) * 100:.1f} %"


def _cell(x: Any) -> str:
    return "" if x is None else str(x).replace("|", "\\|").replace("\n", " ")


def _value(x: Any) -> str:
    if x is None:
        return "(leer)"
    return "''" if x == "" else _cell(x)


def render_facts(profile: dict[str, Any], doc: dict[str, Any], checks: dict[str, Any] | None) -> str:
    lines = [f"# Datenqualitaet: {profile['tabelle']}", ""]
    sample = profile.get("stichprobe_prozent")
    rows = f"{profile['zeilen']:,}".replace(",", ".")
    lines.append(f"Stand {profile['erstellt']}, {rows} Zeilen" + (f" (Stichprobe {sample} %)" if sample else "") + ".")
    if doc.get("beschreibung"):
        lines += ["", doc["beschreibung"].strip()]
    owner = ", ".join(f"{k.capitalize()}: {doc[k]}" for k in ("owner", "steward") if doc.get(k))
    if owner:
        lines += ["", owner]

    lines += ["", "## Spalten", "",
              f"| Spalte | Typ | leer | verschiedene{' (ca.)' if profile.get('verschiedene_geschaetzt') else ''} "
              "| Bereich / Laenge | Bedeutung |",
              "|---|---|---|---|---|---|"]
    for c in profile["spalten"]:
        if "min" in c or "max" in c:
            bereich = f"{_cell(c.get('min'))} bis {_cell(c.get('max'))}"
        elif "min_laenge" in c:
            bereich = f"Laenge {_cell(c.get('min_laenge'))} bis {_cell(c.get('max_laenge'))}"
        else:
            bereich = ""
        bedeutung = (doc["spalten"].get(c["name"]) or {}).get("bedeutung", "")
        key = " 🔑" if "PRIMARY KEY" in c.get("schluessel", []) else ""
        lines.append(f"| {_cell(c['name'])}{key} | {_cell(c['typ'])} | {_pct(c.get('leer_anteil'))} | "
                     f"{_cell(c.get('verschiedene'))} | {bereich} | {_cell(bedeutung)} |")

    notes = []
    for c in profile["spalten"]:
        bits = []
        if c.get("leerstring"):
            bits.append(f"{c['leerstring']} leere Texte ('')")
        if c.get("randleerzeichen"):
            bits.append(f"{c['randleerzeichen']} Werte mit Leerzeichen am Rand")
        if c.get("negativ"):
            bits.append(f"{c['negativ']} negative Werte")
        if c.get("haeufigste_werte"):
            top = ", ".join(f"{_value(v['wert'])} ({v['anzahl']})" for v in c["haeufigste_werte"])
            bits.append(f"haeufigste Werte: {top}")
        if c.get("pii"):
            bits.append("Einzelwerte ausgeblendet (personenbezogen)")
        if bits:
            notes.append(f"- **{c['name']}**: " + "; ".join(bits))
    if notes:
        lines += ["", "## Details pro Spalte", ""] + notes

    if checks and checks.get("regeln"):
        lines += ["", f"## Regeln (Lauf vom {checks['erstellt']})", "",
                  "| Regel | Ausdruck | Verstoesse | Anteil |", "|---|---|---|---|"]
        for r in checks["regeln"]:
            if "fehler" in r:
                lines.append(f"| {r['id']} | `{_cell(r['check'])}` | Fehler: {_cell(r['fehler'])} | |")
            else:
                lines.append(f"| {r['id']} | `{_cell(r['check'])}` | {r['verstoesse']} | {_pct(r['anteil'])} |")

    proposed = [r for r in doc["regeln"] if r.get("status") == "vorgeschlagen"]
    if proposed:
        lines += ["", "## Vorgeschlagene Regeln (noch nicht entschieden)", ""]
        for r in proposed:
            extra = f" Aktuell {r['verstoesse_bei_vorschlag']} Verstoesse." if "verstoesse_bei_vorschlag" in r else ""
            lines.append(f"- **{r['id']}** `{r['check']}`: {r.get('begruendung', '')}{extra}")
    if doc["offene_fragen"]:
        lines += ["", "## Offene Fragen an die Fachabteilung", ""]
        for q in doc["offene_fragen"]:
            col = f" ({q['spalte']})" if q.get("spalte") else ""
            lines.append(f"- **{q['id']}**{col}: {q['frage']}")
    if doc["wissen"]:
        lines += ["", "## Dokumentiertes Wissen", ""]
        for w in doc["wissen"]:
            who = f" ({w['von']})" if w.get("von") else ""
            lines.append(f"- {w.get('datum', '')}{who}: {w['text']}")
    return "\n".join(lines) + "\n"


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def ask_model(profile: dict[str, Any], doc: dict[str, Any], checks: dict[str, Any] | None) -> dict[str, Any]:
    import litellm

    s = get_settings()
    if not s.model:
        raise RuntimeError("SQLPROFIL_MODEL ist nicht gesetzt (siehe .env.example).")
    litellm.drop_params = True  # Modelle ohne response_format sollen nicht scheitern
    payload = {"profil": profile, "dokumentation": doc, "regel_ergebnisse": checks}
    kwargs: dict[str, Any] = {}
    if s.api_base:
        kwargs["api_base"] = s.api_base
    if s.api_key:
        kwargs["api_key"] = s.api_key
    resp = litellm.completion(
        model=s.model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT % {"dialekt": profile.get("dialekt", s.dialect)}},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        **kwargs,
    )
    return _parse_json(resp.choices[0].message.content or "{}")


def merge_model_output(table: str, result: dict[str, Any], validate_on_db: bool = True) -> dict[str, int]:
    """Uebernimmt Vorschlaege und Fragen in die Doku-Datei. Kaputte Regeln fliegen raus."""
    stats = {"regeln_neu": 0, "regeln_verworfen": 0, "fragen_neu": 0}
    for item in result.get("regelvorschlaege") or []:
        check = str(item.get("check", "")).strip()
        try:
            assert_check_expression(check)
            tested = rules.test_rule(table, check) if validate_on_db else None
        except (UnsafeSql, Exception):
            stats["regeln_verworfen"] += 1
            continue
        rule, new = store.add_rule(table, check, str(item.get("begruendung", "")), "vorgeschlagen", "modell")
        if new:
            stats["regeln_neu"] += 1
            if tested is not None:
                doc = store.load(table)
                for r in doc["regeln"]:
                    if r["id"] == rule["id"]:
                        r["verstoesse_bei_vorschlag"] = tested["verstoesse"]
                store.save(doc)
    for item in result.get("fragen") or []:
        frage = str(item.get("frage", "")).strip()
        if frage:
            _, new = store.add_question(table, frage, str(item.get("spalte", "") or ""))
            stats["fragen_neu"] += int(new)
    return stats


def report_path(table: str) -> Path:
    return get_settings().reports_dir / (store.path_for(table).stem + ".md")


def write_report(table: str, use_model: bool = True) -> Path:
    profile = profiler.load_profile(table)
    if profile is None:
        raise RuntimeError(f"Kein Profil fuer {table}. Erst: sqlprofil profile {table}")
    checks = rules.load_results(table)
    assessment = ""
    if use_model:
        result = ask_model(profile, store.load(table), checks)
        merge_model_output(table, result)
        assessment = str(result.get("einschaetzung", "")).strip()
        if assessment:
            from sqlprofil import htmlreport
            htmlreport.save_assessment(table, assessment)
    doc = store.load(table)  # nach dem Merge neu laden, damit Vorschlaege und Fragen im Report stehen
    text = render_facts(profile, doc, checks)
    if assessment:
        text += f"\n## Einschaetzung (Modell, {_dt.date.today().isoformat()})\n\n{assessment}\n"
    p = report_path(table)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p
