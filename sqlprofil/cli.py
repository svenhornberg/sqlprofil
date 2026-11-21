"""Kommandozeile: sqlprofil <befehl> ..."""
from __future__ import annotations

import argparse
import sys

import os
from pathlib import Path

from sqlprofil import htmlreport, patch, profiler, report, rules, store

# Die Statuswerte in den YAML-Dateien sind deutsch, auf der Kommandozeile geht beides.
STATUS_ALIASES = {"accepted": "akzeptiert", "rejected": "abgelehnt", "proposed": "vorgeschlagen",
                  "akzeptiert": "akzeptiert", "abgelehnt": "abgelehnt", "vorgeschlagen": "vorgeschlagen"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sqlprofil", description="Datenqualitaet pro Tabelle")
    ap.add_argument("--demo", metavar="NAME", help="mit einer Demo arbeiten: shop, rental, utilities")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("demo", help="Demo-Daten erzeugen (erfundene Daten mit eingebauten Fehlern)")
    p.add_argument("names", nargs="*", metavar="NAME", help="shop, rental, utilities; ohne Angabe alle")

    sub.add_parser("tables", help="Tabellen der Datenbank auflisten")

    p = sub.add_parser("html", help="HTML-Report fuer eine Tabelle, eine Auswahl oder die ganze Datenbank")
    p.add_argument("tables", nargs="*", metavar="TABELLE", help="ohne Angabe: alle Tabellen mit Doku-Datei")
    p.add_argument("--all", action="store_true", help="jede Tabelle der Datenbank")
    p.add_argument("--with-views", action="store_true", help="bei --all auch Views")
    p.add_argument("--refresh", action="store_true", help="Profile und Regeln vorher neu berechnen")
    p.add_argument("--sample", type=float, metavar="PROZENT")
    p.add_argument("--title", default="")
    p.add_argument("-o", "--output", metavar="DATEI")

    p = sub.add_parser("patch", help="Aenderungsvorschlag aus dem Chat einspielen")
    p.add_argument("datei", help="Datei mit dem Patch, oder - fuer Einfuegen ueber die Standardeingabe")
    p.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts aendern")

    p = sub.add_parser("profile", help="Kennzahlen einer Tabelle berechnen")
    p.add_argument("table", metavar="TABELLE")
    p.add_argument("--sample", type=float, metavar="PROZENT", help="nur einen Teil der Tabelle lesen")

    p = sub.add_parser("check", help="akzeptierte Regeln ausfuehren")
    p.add_argument("table", metavar="TABELLE")

    p = sub.add_parser("report", help="Markdown-Report schreiben")
    p.add_argument("table", metavar="TABELLE")
    p.add_argument("--no-llm", action="store_true", help="nur Fakten, kein Modellaufruf")

    p = sub.add_parser("run", help="profile + check + report")
    p.add_argument("table", metavar="TABELLE")
    p.add_argument("--sample", type=float, metavar="PROZENT")
    p.add_argument("--no-llm", action="store_true")

    p = sub.add_parser("rule", help="Regel akzeptieren oder ablehnen")
    p.add_argument("table", metavar="TABELLE")
    p.add_argument("id")
    p.add_argument("status", choices=list(STATUS_ALIASES))
    p.add_argument("--reason", default="", help="Begruendung, bei Ablehnung dringend empfohlen")

    p = sub.add_parser("answer", help="offene Frage beantworten")
    p.add_argument("table", metavar="TABELLE")
    p.add_argument("id")
    p.add_argument("text")
    p.add_argument("--by", default="", help="wer geantwortet hat")

    args = ap.parse_args(argv)
    if args.demo:
        os.environ["SQLPROFIL_DEMO"] = args.demo
    try:
        if args.cmd == "demo":
            from sqlprofil import demo
            for name in args.names or list(demo.DEMOS):
                print(f"{name}: {demo.build(name)}")
            print("Weiter mit z. B.:  sqlprofil --demo rental tables")
        elif args.cmd == "tables":
            for name, is_view in profiler.list_db_tables():
                print(name + (" (View)" if is_view else ""))
        elif args.cmd == "html":
            return _html(args)
        elif args.cmd == "patch":
            text = sys.stdin.read() if args.datei == "-" else Path(args.datei).read_text(encoding="utf-8")
            lines = patch.apply_ops(patch.parse(text), dry_run=args.dry_run)
            for i, line in enumerate(lines, 1):
                print(f"{i:>2}. {line}")
            print("Nur geprueft, nichts geaendert." if args.dry_run
                  else f"{len(lines)} Aenderungen eingespielt. Jetzt: git diff tables/")
        elif args.cmd == "profile":
            prof = profiler.profile_table(args.table, args.sample)
            print(f"{prof['tabelle']}: {prof['zeilen']} Zeilen, {len(prof['spalten'])} Spalten")
            print(f"Profil: {profiler.profile_path(args.table)}")
            print(f"Doku:   {store.path_for(args.table)}")
        elif args.cmd == "check":
            _print_checks(rules.run_rules(args.table))
        elif args.cmd == "report":
            print(report.write_report(args.table, use_model=not args.no_llm))
        elif args.cmd == "run":
            profiler.profile_table(args.table, args.sample)
            _print_checks(rules.run_rules(args.table))
            print(report.write_report(args.table, use_model=not args.no_llm))
        elif args.cmd == "rule":
            r = store.set_rule_status(args.table, args.id, STATUS_ALIASES[args.status], args.reason)
            print(f"{r['id']} ist jetzt {r['status']}: {r['check']}")
        elif args.cmd == "answer":
            store.answer_question(args.table, args.id, args.text, args.by)
            print(f"Antwort zu {args.id} dokumentiert.")
    except Exception as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    return 0


def _html(args) -> int:
    if args.all:
        tables = [name for name, _ in profiler.list_db_tables(include_views=args.with_views)]
    else:
        tables = args.tables or store.list_tables()
    if not tables:
        print("Keine Tabellen. Namen angeben oder --all verwenden.", file=sys.stderr)
        return 1
    ok, errors = [], {}
    for i, table in enumerate(tables, 1):
        try:
            if args.refresh or profiler.load_profile(table) is None:
                print(f"[{i}/{len(tables)}] Profil {table}", file=sys.stderr)
                profiler.profile_table(table, args.sample)
                rules.run_rules(table)
            ok.append(table)
        except Exception as exc:  # eine nicht lesbare Tabelle soll den Report nicht verhindern
            errors[table] = str(exc).splitlines()[0][:300]
    if not ok:
        print("Keine Tabelle lesbar: " + "; ".join(f"{t}: {m}" for t, m in errors.items()), file=sys.stderr)
        return 1
    out = htmlreport.write_html(ok, Path(args.output) if args.output else None, args.title, errors)
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
