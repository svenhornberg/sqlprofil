import pytest

from sqlprofil import cli, htmlreport, patch, profiler, rules, store

OPS = [
    {"aktion": "tabelle_beschreiben", "tabelle": "auftrag", "beschreibung": "Ein Auftrag pro Zeile", "owner": "Vertrieb"},
    {"aktion": "spalte_dokumentieren", "tabelle": "auftrag", "spalte": "status", "bedeutung": "Bearbeitungsstand",
     "erlaubte_werte": ["offen", "aktiv", "beendet"], "hinweise": "'X' = Altbestand: vor der Migration"},
    {"aktion": "regel_vorschlagen", "tabelle": "auftrag", "check": "betrag >= 0", "begruendung": "keine negativen Betraege"},
    {"aktion": "regel_entscheiden", "tabelle": "auftrag", "regel": "betrag >= 0", "status": "abgelehnt",
     "begruendung": "Gutschriften sind negativ"},
    {"aktion": "wissen_festhalten", "tabelle": "auftrag", "text": "Laufende Auftraege haben kein Ende.", "von": "Fachbereich"},
]


def test_patch_rundreise(duck):
    profiler.profile_table("auftrag")
    text = patch.render(OPS, von="Fachbereich")
    assert text.startswith("# sqlprofil-patch v1")
    assert "#  4. auftrag: Regel betrag >= 0 auf abgelehnt setzen (Gutschriften sind negativ)" in text

    # So kommt der Text aus Chat oder Mail zurueck: mit Vorrede, Code-Zaun und Windows-Zeilenenden
    pasted = "Hallo, hier der Patch:\r\n\r\n```yaml\r\n" + text.replace("\n", "\r\n") + "```\r\nGruss"
    ops = patch.parse(pasted)
    assert [o["aktion"] for o in ops] == [o["aktion"] for o in OPS]

    before = store.path_for("auftrag").read_text(encoding="utf-8")
    assert len(patch.apply_ops(ops, dry_run=True)) == 5
    assert store.path_for("auftrag").read_text(encoding="utf-8") == before  # Pruefen aendert nichts

    patch.apply_ops(ops)
    doc = store.load("auftrag")
    assert doc["owner"] == "Vertrieb" and doc["spalten"]["status"]["erlaubte_werte"] == ["offen", "aktiv", "beendet"]
    assert doc["regeln"][0]["status"] == "abgelehnt" and doc["regeln"][0]["begruendung"] == "Gutschriften sind negativ"
    assert doc["wissen"][0]["von"] == "Fachbereich"


@pytest.mark.parametrize("ops", [
    [{"aktion": "datei_loeschen", "tabelle": "auftrag"}],
    [{"aktion": "spalte_dokumentieren", "tabelle": "auftrag"}],
    [{"aktion": "regel_vorschlagen", "tabelle": "auftrag", "check": "1=1; DROP TABLE auftrag"}],
    [{"aktion": "regel_entscheiden", "tabelle": "auftrag", "regel": "r99", "status": "akzeptiert"}],
    [{"aktion": "wissen_festhalten", "tabelle": "auftrag", "text": "ok"},
     {"aktion": "regel_entscheiden", "tabelle": "auftrag", "regel": "r1", "status": "vielleicht"}],
])
def test_kaputter_patch_aendert_nichts(duck, ops):
    profiler.profile_table("auftrag")
    before = store.path_for("auftrag").read_text(encoding="utf-8")
    with pytest.raises(Exception):
        patch.apply_ops(ops)
    assert store.path_for("auftrag").read_text(encoding="utf-8") == before


def test_html_eine_tabelle(duck):
    profiler.profile_table("auftrag")
    patch.apply_ops(OPS)
    store.add_rule("auftrag", "ende >= beginn", "Ende nie vor Beginn", status="akzeptiert")
    rules.run_rules("auftrag")
    store.document_column("auftrag", "betrag", bedeutung="<script>alert(1)</script>")
    out = htmlreport.write_html(["auftrag"])
    text = out.read_text(encoding="utf-8")
    assert out.name == "main.auftrag.html" and text.startswith("<!DOCTYPE html>")
    assert "<h2>main.auftrag</h2>" in text and 'id="uebersicht"' not in text
    assert "33,3 %" in text and "Gutschriften sind negativ" in text
    assert "<script>alert(1)</script>" not in text and "&lt;script&gt;" in text
    assert "Alpha GmbH" not in text
    assert "http://" not in text and "https://" not in text  # keine externen Abhaengigkeiten


def test_html_ganze_datenbank_ueber_cli(duck, capsys):
    import duckdb
    con = duckdb.connect(str(duck / "test.duckdb"))
    con.execute("CREATE TABLE kunde (id INTEGER, land VARCHAR); INSERT INTO kunde VALUES (1,'DE'),(2,NULL)")
    con.execute("CREATE VIEW v_auftrag AS SELECT * FROM auftrag")
    con.close()
    assert cli.main(["html", "--all", "--title", "Testdatenbank"]) == 0
    out = duck / "reports" / "index.html"
    assert str(out) in capsys.readouterr().out
    text = out.read_text(encoding="utf-8")
    assert "<h1>Testdatenbank</h1>" in text and 'id="uebersicht"' in text
    assert 'href="#t-main-auftrag"' in text and 'href="#t-main-kunde"' in text
    assert "v_auftrag" not in text  # Views nur mit --with-views
    # Auswahl
    assert cli.main(["html", "kunde", "auftrag", "-o", str(duck / "auswahl.html")]) == 0
    assert (duck / "auswahl.html").read_text(encoding="utf-8").count("<section id=\"t-") == 2


def test_cli_patch_pruefen(duck, capsys, tmp_path):
    profiler.profile_table("auftrag")
    f = tmp_path / "p.yaml"
    f.write_text(patch.render(OPS), encoding="utf-8")
    assert cli.main(["patch", str(f), "--dry-run"]) == 0
    assert "Nur geprueft" in capsys.readouterr().out
    assert store.load("auftrag")["owner"] == ""
    assert cli.main(["patch", str(f)]) == 0
    assert store.load("auftrag")["owner"] == "Vertrieb"


@pytest.mark.parametrize("name", ["shop", "rental", "utilities"])
def test_demo(name, tmp_path, monkeypatch):
    from sqlprofil import demo
    monkeypatch.setenv("SQLPROFIL_DEMO_DIR", str(tmp_path))
    out = demo.build(name)
    text = out.read_text(encoding="utf-8")
    assert out == tmp_path / name / "reports" / "index.html" and 'id="uebersicht"' in text
    monkeypatch.setenv("SQLPROFIL_DEMO", name)
    for table in demo.DEMOS[name][3]:
        doc = store.load(table)
        assert doc["beschreibung"] and doc["regeln"]
        results = rules.load_results(table)["regeln"]
        assert results and all("fehler" not in r for r in results)   # jede Demo-Regel ist gueltiges SQL
        assert any(r["verstoesse"] > 0 for r in results)             # und findet eingebaute Fehler
    # Erneutes Bauen liefert dieselben Daten
    first = profiler.load_profile(demo.DEMOS[name][3][0])["spalten"]
    demo.build(name)
    assert profiler.load_profile(demo.DEMOS[name][3][0])["spalten"] == first


def test_cli_englische_befehle(duck, capsys):
    assert cli.main(["profile", "auftrag", "--sample", "100"]) == 0
    store.add_rule("auftrag", "betrag >= 0", "keine negativen Betraege")
    assert cli.main(["rule", "auftrag", "r1", "rejected", "--reason", "Gutschriften sind negativ"]) == 0
    assert store.load("auftrag")["regeln"][0]["status"] == "abgelehnt"
    assert cli.main(["rule", "auftrag", "r1", "accepted"]) == 0
    assert cli.main(["check", "auftrag"]) == 0
    assert "betrag >= 0" in capsys.readouterr().out
    q, _ = store.add_question("auftrag", "Warum fehlt das Ende?")
    assert cli.main(["answer", "auftrag", q["id"], "Laufende Auftraege.", "--by", "Fachbereich"]) == 0
    assert cli.main(["report", "auftrag", "--no-llm"]) == 0
    assert cli.main(["run", "auftrag", "--no-llm"]) == 0
    assert cli.main(["tables"]) == 0
    assert "main.auftrag" in capsys.readouterr().out
