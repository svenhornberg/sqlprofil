"""Der ganze Ablauf gegen eine echte DuckDB: Profil, Regeln, Doku, Report."""
from sqlprofil import profiler, report, rules, store


def _col(profile, name):
    return next(c for c in profile["spalten"] if c["name"] == name)


def test_profil(duck):
    prof = profiler.profile_table("auftrag")
    assert prof["zeilen"] == 6 and prof["dialekt"] == "duckdb"
    ende = _col(prof, "ende")
    assert ende["leer"] == 2 and ende["leer_anteil"] == round(2 / 6, 4)
    status = _col(prof, "status")
    assert status["leerstring"] == 1 and status["randleerzeichen"] == 1
    assert {v["wert"] for v in status["haeufigste_werte"]} >= {"offen", "X"}
    betrag = _col(prof, "betrag")
    assert betrag["typ"] == "decimal" and betrag["negativ"] == 1 and betrag["min"] == -20.0
    assert _col(prof, "storniert")["wahr"] == 1
    assert "PRIMARY KEY" in _col(prof, "id")["schluessel"]
    # Personenbezug: Spaltenname enthaelt "name", also keine Einzelwerte im Profil
    kunde = _col(prof, "kunde_name")
    assert kunde["pii"] is True and "haeufigste_werte" not in kunde
    # Die Doku-Datei wurde mit allen Spalten angelegt
    assert set(store.load("auftrag")["spalten"]) == {c["name"] for c in prof["spalten"]}


def test_regeln_und_doku(duck):
    profiler.profile_table("auftrag")
    assert rules.test_rule("auftrag", "ende >= beginn")["verstoesse"] == 1  # NULL zaehlt nicht
    assert rules.test_rule("auftrag", "ende IS NOT NULL AND ende >= beginn")["verstoesse"] == 3

    r1, new = store.add_rule("auftrag", "ende >= beginn", "Ende nie vor Beginn")
    assert new and r1["id"] == "r1" and r1["status"] == "vorgeschlagen"
    assert rules.run_rules("auftrag")["regeln"] == []  # nur akzeptierte Regeln laufen
    store.set_rule_status("auftrag", "r1", "akzeptiert")
    res = rules.run_rules("auftrag")["regeln"]
    assert res[0]["id"] == "r1" and res[0]["verstoesse"] == 1

    # Abgelehnte Regeln bleiben erhalten und werden nicht noch einmal angelegt
    r2, _ = store.add_rule("auftrag", "betrag >= 0", "keine negativen Betraege")
    store.set_rule_status("auftrag", "r2", "abgelehnt", "Gutschriften sind negativ")
    again, new = store.add_rule("auftrag", "betrag  >=  0")
    assert not new and again["status"] == "abgelehnt" and again["begruendung"] == "Gutschriften sind negativ"

    store.document_column("auftrag", "status", bedeutung="Bearbeitungsstand", hinweise="'X' = Altbestand",
                          erlaubte_werte=["offen", "aktiv", "beendet"])
    q, _ = store.add_question("auftrag", "Warum fehlt bei 2 Auftraegen das Enddatum?", "ende")
    store.answer_question("auftrag", q["id"], "Laufende Auftraege haben kein Ende.", "Fachbereich")
    doc = store.load("auftrag")
    assert doc["offene_fragen"] == [] and doc["wissen"][0]["text"].startswith("Laufende")
    assert doc["spalten"]["status"]["erlaubte_werte"] == ["offen", "aktiv", "beendet"]


def test_report_ohne_modell(duck):
    profiler.profile_table("auftrag")
    store.add_rule("auftrag", "ende >= beginn", "Ende nie vor Beginn", status="akzeptiert")
    rules.run_rules("auftrag")
    text = report.write_report("auftrag", use_model=False).read_text(encoding="utf-8")
    assert "# Datenqualitaet: main.auftrag" in text
    assert "| ende | date | 33.3 % |" in text
    assert "`ende >= beginn` | 1 |" in text
    assert "Alpha GmbH" not in text  # keine personenbezogenen Einzelwerte im Report


def test_modellausgabe_uebernehmen(duck):
    profiler.profile_table("auftrag")
    stats = report.merge_model_output("auftrag", {
        "regelvorschlaege": [
            {"check": "betrag >= 0", "begruendung": "Betraege sollten nicht negativ sein"},
            {"check": "gibt_es_nicht > 0", "begruendung": "Spalte existiert nicht"},
            {"check": "1=1; DROP TABLE auftrag", "begruendung": "boese"},
        ],
        "fragen": [{"spalte": "status", "frage": "Was bedeutet der Status X?"}],
    })
    assert stats == {"regeln_neu": 1, "regeln_verworfen": 2, "fragen_neu": 1}
    doc = store.load("auftrag")
    assert doc["regeln"][0]["verstoesse_bei_vorschlag"] == 1 and doc["regeln"][0]["quelle"] == "modell"
    # Ein zweiter Lauf mit denselben Vorschlaegen aendert nichts
    assert report.merge_model_output("auftrag", {"regelvorschlaege": [{"check": "betrag>=0"}],
                                                 "fragen": [{"frage": "Was bedeutet der Status X?"}]}) == \
        {"regeln_neu": 0, "regeln_verworfen": 0, "fragen_neu": 0}


def test_datenbank_ist_schreibgeschuetzt(duck):
    import pytest
    from sqlprofil.dialects import get_dialect
    with get_dialect().connect() as conn:
        with pytest.raises(Exception):
            conn.execute("DELETE FROM auftrag")
