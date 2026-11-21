"""Kommandozeile: sqlprofil <befehl> ..."""
from __future__ import annotations

import argparse
import sys

import os
from pathlib import Path

from sqlprofil import htmlreport, patch, profiler, report, rules, store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sqlprofil", description="Datenqualitaet pro Tabelle")
    ap.add_argument("--demo", metavar="NAME", help="mit einer Demo arbeiten: shop, vermietung, stadtwerke")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("demo", help="Demo-Daten erzeugen (erfundene Daten mit eingebauten Fehlern)")
    p.add_argument("namen", nargs="*", help="shop, vermietung, stadtwerke; ohne Angabe alle")

    sub.add_parser("tabellen", help="Tabellen der Datenbank auflisten")

    p = sub.add_parser("html", help="HTML-Report fuer eine Tabelle, eine Auswahl oder die ganze Datenbank")
    p.add_argument("tabellen", nargs="*", help="ohne Angabe: alle Tabellen mit Doku-Datei")
    p.add_argument("--alle", action="store_true", help="jede Tabelle der Datenbank")
    p.add_argument("--mit-views", action="store_true", help="bei --alle auch Views")
    p.add_argument("--aktualisieren", action="store_true", help="Profile und Regeln vorher neu berechnen")
    p.add_argument("--stichprobe", type=float, metavar="PROZENT")
    p.add_argument("--titel", default="")
    p.add_argument("-o", "--ausgabe", metavar="DATEI")

    p = sub.add_parser("patch", help="Aenderungsvorschlag aus dem Chat einspielen")
    p.add_argument("datei", help="Datei mit dem Patch, oder - fuer Einfuegen ueber die Standardeingabe")
    p.add_argument("--pruefen", action="store_true", help="nur anzeigen, nichts aendern")

    p = sub.add_parser("profil", help="Kennzahlen einer Tabelle berechnen")
    p.add_argument("tabelle")
    p.add_argument("--stichprobe", type=float, metavar="PROZENT", help="nur einen Teil der Tabelle lesen")

    p = sub.add_parser("pruefen", help="akzeptierte Regeln ausfuehren")
    p.add_argument("tabelle")

    p = sub.add_parser("report", help="Markdown-Report schreiben")
    p.add_argument("tabelle")
    p.add_argument("--ohne-ki", action="store_true", help="nur Fakten, kein Modellaufruf")

    p = sub.add_parser("alles", help="profil + pruefen + report")
    p.add_argument("tabelle")
    p.add_argument("--stichprobe", type=float, metavar="PROZENT")
    p.add_argument("--ohne-ki", action="store_true")

    p = sub.add_parser("regel", help="Regel akzeptieren oder ablehnen")
    p.add_argument("tabelle")
    p.add_argument("id")
    p.add_argument("status", choices=store.RULE_STATUS)
    p.add_argument("--grund", default="", help="Begruendung, bei Ablehnung dringend empfohlen")

    p = sub.add_parser("antwort", help="offene Frage beantworten")
    p.add_argument("tabelle")
    p.add_argument("id")
    p.add_argument("text")
    p.add_argument("--von", default="")

    args = ap.parse_args(argv)
    if args.demo:
        os.environ["SQLPROFIL_DEMO"] = args.demo
    try:
        if args.cmd == "demo":
            from sqlprofil import demo
            for name in args.namen or list(demo.DEMOS):
                print(f"{name}: {demo.build(name)}")
            print("Weiter mit z. B.:  sqlprofil --demo vermietung tabellen")
        elif args.cmd == "tabellen":
            for name, is_view in profiler.list_db_tables():
                print(name + (" (View)" if is_view else ""))
        elif args.cmd == "html":
            return _html(args)
        elif args.cmd == "patch":
            text = sys.stdin.read() if args.datei == "-" else Path(args.datei).read_text(encoding="utf-8")
            lines = patch.apply_ops(patch.parse(text), dry_run=args.pruefen)
            for i, line in enumerate(lines, 1):
                print(f"{i:>2}. {line}")
            print("Nur geprueft, nichts geaendert." if args.pruefen
                  else f"{len(lines)} Aenderungen eingespielt. Jetzt: git diff tables/")
        elif args.cmd == "profil":
            prof = profiler.profile_table(args.tabelle, args.stichprobe)
            print(f"{prof['tabelle']}: {prof['zeilen']} Zeilen, {len(prof['spalten'])} Spalten")
            print(f"Profil: {profiler.profile_path(args.tabelle)}")
            print(f"Doku:   {store.path_for(args.tabelle)}")
        elif args.cmd == "pruefen":
            _print_checks(rules.run_rules(args.tabelle))
        elif args.cmd == "report":
            print(report.write_report(args.tabelle, use_model=not args.ohne_ki))
        elif args.cmd == "alles":
            profiler.profile_table(args.tabelle, args.stichprobe)
            _print_checks(rules.run_rules(args.tabelle))
            print(report.write_report(args.tabelle, use_model=not args.ohne_ki))
        elif args.cmd == "regel":
            r = store.set_rule_status(args.tabelle, args.id, args.status, args.grund)
            print(f"{r['id']} ist jetzt {r['status']}: {r['check']}")
        elif args.cmd == "antwort":
            store.answer_question(args.tabelle, args.id, args.text, args.von)
            print(f"Antwort zu {args.id} dokumentiert.")
    except Exception as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    return 0


def _html(args) -> int:
    if args.alle:
        tables = [name for name, _ in profiler.list_db_tables(include_views=args.mit_views)]
    else:
        tables = args.tabellen or store.list_tables()
    if not tables:
        print("Keine Tabellen. Namen angeben oder --alle verwenden.", file=sys.stderr)
        return 1
    ok, errors = [], {}
    for i, table in enumerate(tables, 1):
        try:
            if args.aktualisieren or profiler.load_profile(table) is None:
                print(f"[{i}/{len(tables)}] Profil {table}", file=sys.stderr)
                profiler.profile_table(table, args.stichprobe)
                rules.run_rules(table)
            ok.append(table)
        except Exception as exc:  # eine nicht lesbare Tabelle soll den Report nicht verhindern
            errors[table] = str(exc).splitlines()[0][:300]
    if not ok:
        print("Keine Tabelle lesbar: " + "; ".join(f"{t}: {m}" for t, m in errors.items()), file=sys.stderr)
        return 1
    out = htmlreport.write_html(ok, Path(args.ausgabe) if args.ausgabe else None, args.titel, errors)
    print(out)
    return 0


def _print_checks(result: dict) -> None:
    if not result["regeln"]:
        print("Keine akzeptierten Regeln.")
    for r in result["regeln"]:
        if "fehler" in r:
            print(f"{r['id']}  FEHLER  {r['check']}  ({r['fehler']})")
        else:
            print(f"{r['id']}  {r['verstoesse']:>8} Verstoesse  {r['check']}")


if __name__ == "__main__":
    raise SystemExit(main())
