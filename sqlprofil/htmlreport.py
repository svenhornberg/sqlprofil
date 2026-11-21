"""HTML-Report fuer eine Tabelle, eine Auswahl oder die ganze Datenbank.

Eine einzige Datei ohne externe Abhaengigkeiten, die man per Mail oder Dateifreigabe weitergeben kann.
Alle Werte aus der Datenbank werden escaped.
"""
from __future__ import annotations

import datetime as _dt
import html
import json
import re
from pathlib import Path
from typing import Any

from sqlprofil import profiler, rules, store
from sqlprofil.config import get_settings

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--mut:#657080;--line:#e2e6ec;--acc:#2f6fde;--ok:#1f8f5f;
--warn:#b7791f;--bad:#c2413b;--bar:#dfe6f3}
@media (prefers-color-scheme:dark){:root{--bg:#12161c;--card:#1a2029;--ink:#e6eaf0;--mut:#93a0b2;
--line:#2a323e;--acc:#7aa7ff;--ok:#5cc797;--warn:#e0b060;--bad:#f0827c;--bar:#2a3546}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:20px;margin:0 0 4px}h3{font-size:15px;margin:22px 0 8px;
color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.sub{color:var(--mut);margin:0 0 20px}a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:20px;margin:0 0 20px}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600;white-space:nowrap}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;
white-space:nowrap}code{font:13px ui-monospace,Consolas,monospace;background:var(--bar);padding:1px 5px;border-radius:4px}
.bar{display:inline-block;width:70px;height:8px;background:var(--bar);border-radius:4px;margin-right:8px;
vertical-align:middle;overflow:hidden}.bar i{display:block;height:100%;background:var(--warn)}
.tag{display:inline-block;font-size:12px;padding:1px 8px;border-radius:10px;border:1px solid var(--line);
color:var(--mut);margin-right:4px}.tag.ok{color:var(--ok);border-color:var(--ok)}
.tag.bad{color:var(--bad);border-color:var(--bad)}.tag.warn{color:var(--warn);border-color:var(--warn)}
.kpis{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0 4px}.kpi{border:1px solid var(--line);border-radius:8px;
padding:8px 14px;min-width:120px}.kpi b{display:block;font-size:20px}.kpi span{color:var(--mut);font-size:12px}
.mut{color:var(--mut)}ul{margin:6px 0;padding-left:20px}.top{float:right;font-size:13px}
.err{color:var(--bad)}td.nw{white-space:nowrap}
"""


def e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _num(n: Any) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return e(n)


def _pct(x: Any) -> str:
    return "" if x is None else f"{float(x) * 100:.1f}".replace(".", ",") + " %"


def _anchor(table: str) -> str:
    return "t-" + re.sub(r"[^\w]", "-", table)


def _md(text: str) -> str:
    """Sehr kleine Markdown-Umsetzung fuer die Modell-Einschaetzung: Absaetze, Listen, fett, Code."""
    out, in_list = [], False
    for raw in text.strip().splitlines():
        line = e(raw.strip())
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"`(.+?)`", r"<code>\1</code>", line)
        bullet = re.match(r"^(?:[-*]|\d+\.)\s+(.*)", line)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{bullet.group(1)}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line:
            out.append(f"<p>{re.sub(r'^#+\s*', '', line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def assessment_path(table: str) -> Path:
    return get_settings().profiles_dir / (store.path_for(table).stem + ".einschaetzung.json")


def save_assessment(table: str, text: str) -> None:
    p = assessment_path(table)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"datum": _dt.date.today().isoformat(), "text": text}, ensure_ascii=False, indent=2),
                 encoding="utf-8")


def load_assessment(table: str) -> dict[str, Any] | None:
    p = assessment_path(table)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def collect(table: str) -> dict[str, Any]:
    """Alles, was es zu einer Tabelle auf der Platte gibt."""
    doc = store.load(table)
    profile = profiler.load_profile(table)
    checks = rules.load_results(table)
    cols = profile["spalten"] if profile else []
    shares = [c["leer_anteil"] for c in cols if c.get("leer_anteil") is not None]
    results = (checks or {}).get("regeln", [])
    return {
        "tabelle": doc["tabelle"], "doc": doc, "profile": profile, "checks": checks,
        "assessment": load_assessment(table),
        "zeilen": profile["zeilen"] if profile else None,
        "spalten": len(cols),
        "leer_mittel": sum(shares) / len(shares) if shares else None,
        "undokumentiert": sum(1 for c in cols if not (doc["spalten"].get(c["name"]) or {}).get("bedeutung")),
        "regeln_aktiv": sum(1 for r in doc["regeln"] if r.get("status") == "akzeptiert"),
        "regeln_offen": sum(1 for r in doc["regeln"] if r.get("status") == "vorgeschlagen"),
        "regeln_verletzt": sum(1 for r in results if r.get("verstoesse")),
        "verstoesse": sum(int(r.get("verstoesse") or 0) for r in results),
        "fragen": len(doc["offene_fragen"]),
    }


def _bar(share: Any) -> str:
    if share is None:
        return ""
    width = max(0.0, min(100.0, float(share) * 100))
    return f'<span class="bar"><i style="width:{width:.1f}%"></i></span>{_pct(share)}'


def _range(c: dict[str, Any]) -> str:
    if "min" in c or "max" in c:
        return f"{e(c.get('min'))} bis {e(c.get('max'))}"
    if "min_laenge" in c:
        return f"Länge {e(c.get('min_laenge'))} bis {e(c.get('max_laenge'))}"
    if "wahr" in c:
        return f"{_num(c.get('wahr') or 0)} × wahr"
    return ""


def _notes(c: dict[str, Any], entry: dict[str, Any]) -> str:
    bits = []
    if entry.get("bedeutung"):
        bits.append(e(entry["bedeutung"]))
    if entry.get("erlaubte_werte"):
        bits.append("Erlaubt: " + ", ".join(f"<code>{e(v)}</code>" for v in entry["erlaubte_werte"]))
    if entry.get("hinweise"):
        bits.append(f'<span class="mut">{e(entry["hinweise"])}</span>')
    flags = []
    if c.get("leerstring"):
        flags.append(f"{_num(c['leerstring'])} leere Texte")
    if c.get("randleerzeichen"):
        flags.append(f"{_num(c['randleerzeichen'])} mit Leerzeichen am Rand")
    if c.get("negativ"):
        flags.append(f"{_num(c['negativ'])} negativ")
    if flags:
        bits.append('<span class="tag warn">' + '</span><span class="tag warn">'.join(flags) + "</span>")
    if c.get("haeufigste_werte"):
        bits.append('<span class="mut">Häufig: ' + ", ".join(
            f"{'∅' if v['wert'] is None else ('<code>leer</code>' if v['wert'] == '' else e(v['wert']))} ({_num(v['anzahl'])})"
            for v in c["haeufigste_werte"]) + "</span>")
    if c.get("pii"):
        bits.append('<span class="tag">Einzelwerte ausgeblendet</span>')
    return "<br>".join(bits)


def render_table(info: dict[str, Any], with_top_link: bool) -> str:
    doc, profile, checks = info["doc"], info["profile"], info["checks"]
    out = [f'<section id="{_anchor(info["tabelle"])}">']
    if with_top_link:
        out.append('<a class="top" href="#uebersicht">↑ Übersicht</a>')
    out.append(f"<h2>{e(info['tabelle'])}</h2>")
    meta = []
    if profile:
        meta.append(f"Profil vom {e(profile['erstellt'])}")
        if profile.get("stichprobe_prozent"):
            meta.append(f"Stichprobe {e(profile['stichprobe_prozent'])} %")
    meta += [f"{k.capitalize()}: {e(doc[k])}" for k in ("owner", "steward") if doc.get(k)]
    out.append(f'<p class="sub">{" · ".join(meta) or "Noch kein Profil vorhanden."}</p>')
    if doc.get("beschreibung"):
        out.append(f"<p>{e(doc['beschreibung'])}</p>")

    if profile:
        out.append('<div class="kpis">'
                   f'<div class="kpi"><b>{_num(info["zeilen"])}</b><span>Zeilen</span></div>'
                   f'<div class="kpi"><b>{info["spalten"]}</b><span>Spalten</span></div>'
                   f'<div class="kpi"><b>{_pct(info["leer_mittel"]) or "–"}</b><span>leer im Mittel</span></div>'
                   f'<div class="kpi"><b>{info["undokumentiert"]}</b><span>Spalten ohne Erklärung</span></div>'
                   f'<div class="kpi"><b>{_num(info["verstoesse"])}</b><span>Regelverstöße</span></div>'
                   f'<div class="kpi"><b>{info["fragen"]}</b><span>offene Fragen</span></div></div>')
        out.append('<h3>Spalten</h3><div class="scroll"><table><tr><th>Spalte</th><th>Typ</th><th>leer</th>'
                   f'<th class="n">verschiedene{" (ca.)" if profile.get("verschiedene_geschaetzt") else ""}</th><th>Bereich</th><th>Bedeutung und Auffälligkeiten</th></tr>')
        for c in profile["spalten"]:
            keys = "".join(f'<span class="tag">{e(k)}</span>' for k in c.get("schluessel", []))
            out.append(f"<tr><td><b>{e(c['name'])}</b> {keys}</td><td>{e(c['typ'])}</td><td class='nw'>{_bar(c.get('leer_anteil'))}</td>"
                       f"<td class=\"n\">{_num(c['verschiedene']) if c.get('verschiedene') is not None else ''}</td>"
                       f"<td class='nw'>{_range(c)}</td><td>{_notes(c, doc['spalten'].get(c['name']) or {})}</td></tr>")
        out.append("</table></div>")

    if doc["regeln"]:
        results = {r["id"]: r for r in (checks or {}).get("regeln", [])}
        out.append('<h3>Regeln</h3><div class="scroll"><table><tr><th>ID</th><th>Status</th><th>Ausdruck</th>'
                   '<th class="n">Verstöße</th><th class="n">Anteil</th><th>Begründung</th></tr>')
        for r in doc["regeln"]:
            res = results.get(r["id"], {})
            status = r.get("status", "")
            cls = {"akzeptiert": "ok", "abgelehnt": "", "vorgeschlagen": "warn"}.get(status, "")
            if "fehler" in res:
                viol, share = f'<span class="err">Fehler: {e(res["fehler"])}</span>', ""
            elif "verstoesse" in res:
                viol, share = _num(res["verstoesse"]), _pct(res.get("anteil"))
            elif "verstoesse_bei_vorschlag" in r:
                viol, share = f'{_num(r["verstoesse_bei_vorschlag"])} <span class="mut">(bei Vorschlag)</span>', ""
            else:
                viol, share = "", ""
            out.append(f'<tr><td>{e(r["id"])}</td><td><span class="tag {cls}">{e(status)}</span></td>'
                       f'<td><code>{e(r["check"])}</code></td><td class="n">{viol}</td><td class="n">{share}</td>'
                       f'<td>{e(r.get("begruendung", ""))}</td></tr>')
        out.append("</table></div>")

    if doc["offene_fragen"]:
        out.append("<h3>Offene Fragen an die Fachabteilung</h3><ul>")
        for q in doc["offene_fragen"]:
            col = f" <span class=\"tag\">{e(q['spalte'])}</span>" if q.get("spalte") else ""
            out.append(f"<li><b>{e(q['id'])}</b>{col} {e(q['frage'])}</li>")
        out.append("</ul>")
    if doc["wissen"]:
        out.append("<h3>Dokumentiertes Wissen</h3><ul>")
        for w in doc["wissen"]:
            who = f" ({e(w['von'])})" if w.get("von") else ""
            frage = f'<span class="mut">{e(w["frage"])}</span><br>' if w.get("frage") else ""
            out.append(f'<li>{frage}{e(w["text"])} <span class="mut">{e(w.get("datum", ""))}{who}</span></li>')
        out.append("</ul>")
    if info["assessment"]:
        out.append(f'<h3>Einschätzung des Modells ({e(info["assessment"]["datum"])})</h3>{_md(info["assessment"]["text"])}')
    out.append("</section>")
    return "\n".join(out)


def render_overview(infos: list[dict[str, Any]], errors: dict[str, str]) -> str:
    out = ['<section id="uebersicht"><h2>Übersicht</h2><div class="scroll"><table><tr><th>Tabelle</th>'
           '<th class="n">Zeilen</th><th class="n">Spalten</th><th>leer im Mittel</th>'
           '<th class="n">ohne Erklärung</th><th class="n">Regeln aktiv</th><th class="n">Verstöße</th>'
           '<th class="n">Vorschläge</th><th class="n">offene Fragen</th></tr>']
    for i in infos:
        out.append(f'<tr><td><a href="#{_anchor(i["tabelle"])}">{e(i["tabelle"])}</a></td>'
                   f'<td class="n">{_num(i["zeilen"]) if i["zeilen"] is not None else "–"}</td>'
                   f'<td class="n">{i["spalten"] or "–"}</td><td class="nw">{_bar(i["leer_mittel"])}</td>'
                   f'<td class="n">{i["undokumentiert"]}</td><td class="n">{i["regeln_aktiv"]}</td>'
                   f'<td class="n">{_num(i["verstoesse"])}</td><td class="n">{i["regeln_offen"]}</td>'
                   f'<td class="n">{i["fragen"]}</td></tr>')
    out.append("</table></div>")
    if errors:
        out.append("<h3>Nicht lesbar</h3><ul>" + "".join(
            f'<li><b>{e(t)}</b> <span class="err">{e(msg)}</span></li>' for t, msg in errors.items()) + "</ul>")
    out.append("</section>")
    return "\n".join(out)


def render_html(tables: list[str], title: str = "", errors: dict[str, str] | None = None) -> str:
    infos = [collect(t) for t in tables]
    many = len(infos) != 1 or bool(errors)
    title = title or (infos[0]["tabelle"] if len(infos) == 1 else "Datenqualität")
    s = get_settings()
    parts = [f'<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
             f'<meta name="viewport" content="width=device-width,initial-scale=1">'
             f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>",
             f"<h1>{e(title)}</h1>",
             f'<p class="sub">Erzeugt am {_dt.datetime.now().strftime("%d.%m.%Y %H:%M")} · {len(infos)} '
             f'Tabelle{"n" if len(infos) != 1 else ""} · Datenbank: {e(s.dialect)}</p>']
    if many:
        parts.append(render_overview(infos, errors or {}))
    parts += [render_table(i, with_top_link=many) for i in infos]
    parts.append("</main></body></html>")
    return "\n".join(parts)


def write_html(tables: list[str], out: Path | None = None, title: str = "",
               errors: dict[str, str] | None = None) -> Path:
    if out is None:
        name = store.path_for(tables[0]).stem if len(tables) == 1 else "index"
        out = get_settings().reports_dir / f"{name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(tables, title, errors), encoding="utf-8")
    return out
