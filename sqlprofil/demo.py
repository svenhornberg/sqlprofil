"""Demo-Modus: erfundene Daten aus drei Branchen, mit absichtlich eingebauten Datenfehlern.

Alle Namen, Nummern und Werte sind zufaellig erzeugt und frei erfunden. Die Daten liegen in einer
DuckDB-Datei, es wird keine weitere Datenbank gebraucht.

    sqlprofil demo                 baut alle drei Demos unter demo/
    sqlprofil --demo shop html     arbeitet danach mit der Shop-Demo
    SQLPROFIL_DEMO=vermietung adk web agents
"""
from __future__ import annotations

import datetime as _dt
import os
import random
from pathlib import Path
from typing import Any, Callable

from sqlprofil import htmlreport, patch, profiler, rules
from sqlprofil.config import demo_root

STICHTAG = _dt.date(2025, 12, 31)


def _day(rng: random.Random, back: int, forward: int = 0) -> _dt.date:
    return STICHTAG + _dt.timedelta(days=rng.randint(-back, forward))


def _load(con: Any, table: str, rows: list[tuple]) -> None:
    """Zeilen ueber eine temporaere CSV-Datei laden, das ist um Groessenordnungen schneller als einzelne INSERTs."""
    import csv
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{table}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
            for row in rows:
                # None bleibt ein unquotiertes leeres Feld (NULL), "" wird als "" geschrieben (leerer Text)
                w.writerow(["\x00NULL" if v is None else (str(v) if isinstance(v, (_dt.date, bool)) else v) for v in row])
        text = path.read_text(encoding="utf-8").replace('"\x00NULL"', "")
        path.write_text(text, encoding="utf-8")
        con.execute(f"COPY {table} FROM '{path.as_posix()}' "
                    "(FORMAT csv, HEADER false, NULLSTR '', ALLOW_QUOTED_NULLS false)")


def _some(rng: random.Random, share: float) -> bool:
    return rng.random() < share


# ---------------------------------------------------------------- Onlineshop

def _shop(con: Any, rng: random.Random) -> None:
    con.execute("""
        CREATE TABLE kunde (kunde_id INTEGER PRIMARY KEY, email VARCHAR, land VARCHAR, registriert_am DATE,
                            newsletter BOOLEAN, geburtsjahr INTEGER);
        CREATE TABLE produkt (produkt_id INTEGER PRIMARY KEY, bezeichnung VARCHAR, kategorie VARCHAR,
                              preis DECIMAL(10,2), bestand INTEGER, aktiv BOOLEAN);
        CREATE TABLE bestellung (bestell_id INTEGER PRIMARY KEY, kunde_id INTEGER, bestellt_am DATE,
                                 versendet_am DATE, status VARCHAR, zahlart VARCHAR, summe DECIMAL(10,2));
        CREATE TABLE bestellposition (position_id INTEGER PRIMARY KEY, bestell_id INTEGER, produkt_id INTEGER,
                                      menge INTEGER, einzelpreis DECIMAL(10,2));
    """)
    laender = ["DE"] * 60 + ["AT"] * 12 + ["CH"] * 8 + ["NL"] * 5 + ["Deutschland"] * 6 + ["de"] * 4 + [" DE"] * 2 + [""] * 3
    kunden = []
    for i in range(1, 1501):
        mail = f"kunde{i}@beispiel.example" if not _some(rng, 0.02) else f"kunde{rng.randint(1, 50)}@beispiel.example"
        jahr = rng.randint(1950, 2006)
        if _some(rng, 0.015):
            jahr = rng.choice([1900, 0, 2099])
        kunden.append((i, None if _some(rng, 0.01) else mail, rng.choice(laender), _day(rng, 1500),
                       None if _some(rng, 0.2) else _some(rng, 0.4), None if _some(rng, 0.3) else jahr))
    _load(con, "kunde", kunden)

    kategorien = ["Haushalt", "Garten", "Werkzeug", "Elektronik", "Spielwaren", "Buero"]
    dinge = ["Lampe", "Schere", "Kabel", "Regal", "Box", "Set", "Halter", "Matte", "Leiste", "Koffer"]
    produkte = []
    for i in range(1, 301):
        preis = round(rng.uniform(2, 400), 2)
        if _some(rng, 0.03):
            preis = 0.0
        bestand = rng.randint(0, 500)
        if _some(rng, 0.04):
            bestand = -rng.randint(1, 20)
        kat = rng.choice(kategorien)
        if _some(rng, 0.05):
            kat = rng.choice([kat.upper(), kat + " ", None])
        produkte.append((i, f"{rng.choice(dinge)} {rng.choice('ABCDEFGH')}{rng.randint(10, 99)}", kat, preis, bestand,
                         _some(rng, 0.9)))
    _load(con, "produkt", produkte)

    status = ["versendet"] * 70 + ["offen"] * 12 + ["storniert"] * 8 + ["retoure"] * 6 + ["Versendet"] * 3 + ["?"]
    bestellungen, positionen, pos_id = [], [], 1
    for i in range(1, 4001):
        bestellt = _day(rng, 900)
        st = rng.choice(status)
        versendet = bestellt + _dt.timedelta(days=rng.randint(0, 6)) if st.lower() in {"versendet", "retoure"} else None
        if versendet and _some(rng, 0.03):
            versendet = bestellt - _dt.timedelta(days=rng.randint(1, 30))  # Versand vor Bestellung
        if st == "versendet" and _some(rng, 0.04):
            versendet = None  # versendet ohne Datum
        kunde = rng.randint(1, 1500) if not _some(rng, 0.01) else rng.randint(9000, 9100)  # Kunde gibt es nicht
        summe = 0.0
        for _ in range(rng.randint(1, 4)):
            p = rng.choice(produkte)
            menge = rng.randint(1, 5) if not _some(rng, 0.02) else 0
            positionen.append((pos_id, i, p[0], menge, p[3]))
            summe += menge * p[3]
            pos_id += 1
        if _some(rng, 0.03):
            summe = summe + rng.uniform(5, 50)  # Summe passt nicht zu den Positionen
        bestellungen.append((i, kunde, bestellt, versendet, st,
                             rng.choice(["Karte", "Rechnung", "PayPal", "Vorkasse", "", None]), round(summe, 2)))
    _load(con, "bestellung", bestellungen)
    _load(con, "bestellposition", positionen)


SHOP_OPS = [
    {"aktion": "tabelle_beschreiben", "tabelle": "bestellung", "beschreibung": "Eine Zeile pro Kundenbestellung im Onlineshop.",
     "owner": "Leitung E-Commerce", "steward": "Kundenservice"},
    {"aktion": "spalte_dokumentieren", "tabelle": "bestellung", "spalte": "status", "bedeutung": "Bearbeitungsstand der Bestellung",
     "erlaubte_werte": ["offen", "versendet", "storniert", "retoure"]},
    {"aktion": "spalte_dokumentieren", "tabelle": "bestellung", "spalte": "summe",
     "bedeutung": "Rechnungsbetrag inklusive Versand", "hinweise": "Kann von der Summe der Positionen abweichen (Versandkosten, Gutscheine)."},
    {"aktion": "regel_vorschlagen", "tabelle": "bestellung", "check": "versendet_am >= bestellt_am",
     "begruendung": "Versand kann nicht vor der Bestellung liegen"},
    {"aktion": "regel_entscheiden", "tabelle": "bestellung", "regel": "versendet_am >= bestellt_am", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "bestellung", "check": "status IN ('offen', 'versendet', 'storniert', 'retoure')",
     "begruendung": "Nur die vier definierten Status"},
    {"aktion": "regel_entscheiden", "tabelle": "bestellung", "regel": "status IN ('offen', 'versendet', 'storniert', 'retoure')",
     "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "bestellung", "check": "status <> 'versendet' OR versendet_am IS NOT NULL",
     "begruendung": "Versendete Bestellungen brauchen ein Versanddatum"},
    {"aktion": "frage_stellen", "tabelle": "bestellung", "spalte": "zahlart",
     "frage": "Bei einem Teil der Bestellungen fehlt die Zahlart. Sind das Gastbestellungen oder ein Fehler im Checkout?"},
    {"aktion": "tabelle_beschreiben", "tabelle": "produkt", "beschreibung": "Artikelstamm.", "owner": "Einkauf"},
    {"aktion": "regel_vorschlagen", "tabelle": "produkt", "check": "bestand >= 0", "begruendung": "Lagerbestand kann nicht negativ sein"},
    {"aktion": "regel_entscheiden", "tabelle": "produkt", "regel": "bestand >= 0", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "produkt", "check": "preis > 0", "begruendung": "Jeder Artikel hat einen Preis"},
    {"aktion": "regel_entscheiden", "tabelle": "produkt", "regel": "preis > 0", "status": "abgelehnt",
     "begruendung": "Gratisbeigaben werden bewusst mit Preis 0 gefuehrt."},
    {"aktion": "tabelle_beschreiben", "tabelle": "kunde", "beschreibung": "Registrierte Kundenkonten.", "owner": "Marketing"},
    {"aktion": "spalte_dokumentieren", "tabelle": "kunde", "spalte": "land", "bedeutung": "Lieferland als ISO-Code mit zwei Buchstaben"},
    {"aktion": "regel_vorschlagen", "tabelle": "kunde", "check": "land IN ('DE', 'AT', 'CH', 'NL')",
     "begruendung": "Es wird nur in diese Laender geliefert, Schreibweise als ISO-Code"},
    {"aktion": "regel_entscheiden", "tabelle": "kunde", "regel": "land IN ('DE', 'AT', 'CH', 'NL')", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "kunde", "check": "geburtsjahr BETWEEN 1920 AND 2010",
     "begruendung": "Plausibles Geburtsjahr"},
    {"aktion": "wissen_festhalten", "tabelle": "kunde", "von": "Marketing",
     "text": "Das Geburtsjahr ist seit 2023 kein Pflichtfeld mehr, deshalb fehlt es bei neueren Konten oft."},
    {"aktion": "tabelle_beschreiben", "tabelle": "bestellposition", "beschreibung": "Einzelne Artikel einer Bestellung.",
     "owner": "Leitung E-Commerce"},
    {"aktion": "regel_vorschlagen", "tabelle": "bestellposition", "check": "menge > 0", "begruendung": "Position ohne Menge ist sinnlos"},
    {"aktion": "regel_entscheiden", "tabelle": "bestellposition", "regel": "menge > 0", "status": "akzeptiert"},
]


# ------------------------------------------------- Baumaschinen-Vermietung

def _vermietung(con: Any, rng: random.Random) -> None:
    con.execute("""
        CREATE TABLE geraet (geraet_id INTEGER PRIMARY KEY, inventarnummer VARCHAR, geraetetyp VARCHAR,
                             hersteller VARCHAR, baujahr INTEGER, betriebsstunden INTEGER, standort VARCHAR,
                             status VARCHAR, naechste_pruefung DATE);
        CREATE TABLE mietvertrag (vertrag_id INTEGER PRIMARY KEY, kunde_nr INTEGER, geraet_id INTEGER,
                                  mietbeginn DATE, mietende DATE, rueckgabe_am DATE, tagespreis DECIMAL(10,2),
                                  status VARCHAR, baustelle_plz VARCHAR);
        CREATE TABLE wartung (wartung_id INTEGER PRIMARY KEY, geraet_id INTEGER, datum DATE, art VARCHAR,
                              kosten DECIMAL(10,2), betriebsstunden_stand INTEGER);
    """)
    typen = {"Minibagger": 140, "Radlader": 190, "Teleskoplader": 210, "Ruettelplatte": 35, "Arbeitsbuehne": 120,
             "Stromerzeuger": 60, "Walze": 150, "Bauaufzug": 90}
    hersteller = ["Nordbau", "Terratec", "Kranwerk", "Hubtec", "Feldmann", "Loewen Maschinen"]
    standorte = ["Nord", "Sued", "West", "Ost", "Mitte"]
    stati = ["verfuegbar"] * 45 + ["vermietet"] * 35 + ["werkstatt"] * 8 + ["Vermietet"] * 4 + ["VERMIETET"] * 2 + ["verm."] * 2 + ["ausgemustert"] * 4
    geraete = []
    for i in range(1, 801):
        typ = rng.choice(list(typen))
        baujahr = rng.randint(2010, 2025)
        if _some(rng, 0.02):
            baujahr = rng.choice([0, 1900, 2099])
        stunden = rng.randint(0, 9000)
        if _some(rng, 0.02):
            stunden = -1
        if _some(rng, 0.01):
            stunden = 999999
        pruefung = _day(rng, 60, 365)
        if _some(rng, 0.06):
            pruefung = _day(rng, 700, -90)  # Pruefung laengst ueberfaellig
        inv = f"{typ[:2].upper()}-{i:05d}" if not _some(rng, 0.02) else f"{typ[:2].upper()}-{rng.randint(1, 30):05d}"
        geraete.append((i, inv, typ if not _some(rng, 0.03) else typ.lower(),
                        None if _some(rng, 0.05) else rng.choice(hersteller), baujahr, stunden,
                        rng.choice(standorte) if not _some(rng, 0.03) else "", rng.choice(stati),
                        None if _some(rng, 0.04) else pruefung))
    _load(con, "geraet", geraete)

    vertraege = []
    for i in range(1, 5001):
        g = rng.choice(geraete)
        geraet_id = g[0] if not _some(rng, 0.01) else rng.randint(5000, 5100)  # Geraet gibt es nicht
        beginn = _day(rng, 720, 20)
        ende = beginn + _dt.timedelta(days=rng.randint(1, 60))
        if _some(rng, 0.025):
            ende = beginn - _dt.timedelta(days=rng.randint(1, 20))  # Ende vor Beginn
        beendet = ende < STICHTAG
        rueckgabe = ende + _dt.timedelta(days=rng.randint(-2, 5)) if beendet else None
        st = "beendet" if beendet else ("aktiv" if beginn <= STICHTAG else "reserviert")
        if st == "aktiv" and _some(rng, 0.15):
            rueckgabe = _day(rng, 20)  # aktiv, aber schon zurueckgegeben
        if st == "beendet" and _some(rng, 0.04):
            rueckgabe = None  # beendet ohne Rueckgabe
        preis = float(typen.get(g[2].capitalize(), 100)) * rng.uniform(0.8, 1.2)
        if _some(rng, 0.02):
            preis = 0.0
        plz = f"{rng.randint(1000, 99999):05d}"
        if _some(rng, 0.04):
            plz = plz[1:]  # fuehrende Null verloren
        if _some(rng, 0.03):
            plz = None
        vertraege.append((i, rng.randint(10000, 12500), geraet_id, beginn, ende, rueckgabe, round(preis, 2), st, plz))
    _load(con, "mietvertrag", vertraege)

    arten = ["Inspektion"] * 5 + ["Reparatur"] * 3 + ["UVV-Pruefung"] * 3 + ["inspektion", "Rep.", ""]
    wartungen = []
    for i in range(1, 2501):
        g = rng.choice(geraete)
        kosten = round(rng.uniform(40, 2500), 2)
        if _some(rng, 0.03):
            kosten = -kosten  # Gutschrift oder Vorzeichenfehler?
        wartungen.append((i, g[0], _day(rng, 900, 30 if _some(rng, 0.02) else 0), rng.choice(arten),
                          None if _some(rng, 0.08) else kosten,
                          None if _some(rng, 0.2) else max(0, g[5] - rng.randint(0, 3000))))
    _load(con, "wartung", wartungen)


VERMIETUNG_OPS = [
    {"aktion": "tabelle_beschreiben", "tabelle": "geraet", "beschreibung": "Mietpark: jede Maschine, die vermietet werden kann.",
     "owner": "Leitung Mietpark", "steward": "Disposition"},
    {"aktion": "spalte_dokumentieren", "tabelle": "geraet", "spalte": "status", "bedeutung": "Wo die Maschine gerade ist",
     "erlaubte_werte": ["verfuegbar", "vermietet", "werkstatt", "ausgemustert"]},
    {"aktion": "spalte_dokumentieren", "tabelle": "geraet", "spalte": "betriebsstunden",
     "bedeutung": "Zaehlerstand bei der letzten Rueckgabe", "hinweise": "Ruettelplatten haben keinen Zaehler, dort steht 0."},
    {"aktion": "spalte_dokumentieren", "tabelle": "geraet", "spalte": "naechste_pruefung",
     "bedeutung": "Termin der naechsten gesetzlichen Sicherheitspruefung"},
    {"aktion": "regel_vorschlagen", "tabelle": "geraet", "check": "status IN ('verfuegbar', 'vermietet', 'werkstatt', 'ausgemustert')",
     "begruendung": "Nur die vier definierten Status, einheitlich klein geschrieben"},
    {"aktion": "regel_entscheiden", "tabelle": "geraet", "regel": "status IN ('verfuegbar', 'vermietet', 'werkstatt', 'ausgemustert')",
     "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "geraet", "check": "baujahr BETWEEN 1990 AND 2026", "begruendung": "Plausibles Baujahr"},
    {"aktion": "regel_entscheiden", "tabelle": "geraet", "regel": "baujahr BETWEEN 1990 AND 2026", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "geraet", "check": "betriebsstunden BETWEEN 0 AND 50000",
     "begruendung": "Negative oder absurd hohe Zaehlerstaende sind Eingabefehler"},
    {"aktion": "regel_entscheiden", "tabelle": "geraet", "regel": "betriebsstunden BETWEEN 0 AND 50000", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "geraet",
     "check": "status = 'ausgemustert' OR naechste_pruefung >= DATE '2025-12-31'",
     "begruendung": "Kein Geraet im Bestand darf eine ueberfaellige Sicherheitspruefung haben"},
    {"aktion": "frage_stellen", "tabelle": "geraet", "spalte": "inventarnummer",
     "frage": "Einige Inventarnummern kommen doppelt vor. Wurden Nummern ausgemusterter Geraete neu vergeben?"},
    {"aktion": "tabelle_beschreiben", "tabelle": "mietvertrag", "beschreibung": "Eine Zeile pro Mietvorgang eines Geraets.",
     "owner": "Vertriebsinnendienst"},
    {"aktion": "spalte_dokumentieren", "tabelle": "mietvertrag", "spalte": "mietende",
     "bedeutung": "Vereinbartes Ende laut Vertrag", "hinweise": "Die tatsaechliche Rueckgabe steht in rueckgabe_am."},
    {"aktion": "regel_vorschlagen", "tabelle": "mietvertrag", "check": "mietende >= mietbeginn", "begruendung": "Ende nie vor Beginn"},
    {"aktion": "regel_entscheiden", "tabelle": "mietvertrag", "regel": "mietende >= mietbeginn", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "mietvertrag", "check": "status <> 'aktiv' OR rueckgabe_am IS NULL",
     "begruendung": "Ein aktiver Vertrag kann noch keine Rueckgabe haben"},
    {"aktion": "regel_entscheiden", "tabelle": "mietvertrag", "regel": "status <> 'aktiv' OR rueckgabe_am IS NULL", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "mietvertrag", "check": "LENGTH(baustelle_plz) = 5",
     "begruendung": "Postleitzahlen haben fuenf Stellen, fuehrende Nullen gehen beim Import verloren"},
    {"aktion": "regel_entscheiden", "tabelle": "mietvertrag", "regel": "LENGTH(baustelle_plz) = 5", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "mietvertrag", "check": "tagespreis > 0", "begruendung": "Jede Miete hat einen Preis"},
    {"aktion": "regel_entscheiden", "tabelle": "mietvertrag", "regel": "tagespreis > 0", "status": "abgelehnt",
     "begruendung": "Ersatzgeraete bei Ausfall werden kostenlos gestellt und mit 0 gefuehrt."},
    {"aktion": "frage_stellen", "tabelle": "mietvertrag", "spalte": "rueckgabe_am",
     "frage": "Bei manchen beendeten Vertraegen fehlt das Rueckgabedatum. Wird die Rueckgabe dort nicht gebucht?"},
    {"aktion": "tabelle_beschreiben", "tabelle": "wartung", "beschreibung": "Werkstattvorgaenge je Geraet.", "owner": "Werkstattleitung"},
    {"aktion": "regel_vorschlagen", "tabelle": "wartung", "check": "datum <= DATE '2025-12-31'",
     "begruendung": "Erledigte Wartungen liegen nicht in der Zukunft"},
    {"aktion": "regel_entscheiden", "tabelle": "wartung", "regel": "datum <= DATE '2025-12-31'", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "wartung", "check": "kosten >= 0", "begruendung": "Kosten sind nicht negativ"},
    {"aktion": "wissen_festhalten", "tabelle": "wartung", "von": "Werkstattleitung",
     "text": "Vor 2024 wurde der Zaehlerstand bei Wartungen nicht erfasst, deshalb fehlt er bei aelteren Eintraegen."},
]


# ---------------------------------------------------------------- Stadtwerke

def _stadtwerke(con: Any, rng: random.Random) -> None:
    con.execute("""
        CREATE TABLE zaehler (zaehler_id INTEGER PRIMARY KEY, zaehlernummer VARCHAR, sparte VARCHAR, einbau_am DATE,
                              eichung_gueltig_bis DATE, ortsteil VARCHAR, status VARCHAR);
        CREATE TABLE vertrag (vertrag_id INTEGER PRIMARY KEY, zaehler_id INTEGER, tarif VARCHAR, beginn DATE, ende DATE,
                              abschlag DECIMAL(10,2), zahlweise VARCHAR);
        CREATE TABLE ablesung (ablesung_id INTEGER PRIMARY KEY, zaehler_id INTEGER, datum DATE, stand DECIMAL(12,1),
                               art VARCHAR, einheit VARCHAR);
    """)
    sparten = ["Strom"] * 50 + ["Gas"] * 25 + ["Wasser"] * 20 + ["strom"] * 3 + ["STROM"] * 1 + ["Waerme"] * 1
    einheit = {"strom": "kWh", "gas": "m3", "wasser": "m3", "waerme": "kWh"}
    zaehler = []
    for i in range(1, 2001):
        sp = rng.choice(sparten)
        einbau = _day(rng, 6000, -30)
        eichung = einbau + _dt.timedelta(days=365 * rng.choice([6, 8, 16]))
        if _some(rng, 0.02):
            eichung = einbau - _dt.timedelta(days=rng.randint(10, 400))  # Eichung vor Einbau
        zaehler.append((i, f"{sp[0].upper()}{rng.randint(10**7, 10**8 - 1)}", sp, einbau,
                        None if _some(rng, 0.05) else eichung,
                        rng.choice(["Altstadt", "Nordviertel", "Hafen", "Suedhang", "Neubaugebiet", "altstadt", ""]),
                        rng.choice(["aktiv"] * 9 + ["ausgebaut", "gesperrt"])))
    _load(con, "zaehler", zaehler)

    vertraege = []
    for i in range(1, 2601):
        z = rng.choice(zaehler)
        beginn = _day(rng, 3000)
        ende = None if _some(rng, 0.7) else beginn + _dt.timedelta(days=rng.randint(30, 2000))
        if ende and _some(rng, 0.04):
            ende = beginn - _dt.timedelta(days=rng.randint(1, 90))
        abschlag = round(rng.uniform(20, 260), 2)
        if _some(rng, 0.03):
            abschlag = rng.choice([0.0, -abschlag])
        vertraege.append((i, z[0] if not _some(rng, 0.01) else rng.randint(8000, 8100),
                          rng.choice(["Basis", "Komfort", "Oeko", "Gewerbe", "basis", None]), beginn, ende, abschlag,
                          rng.choice(["monatlich"] * 8 + ["jaehrlich", "", "mtl."])))
    _load(con, "vertrag", vertraege)

    ablesungen = []
    for i in range(1, 8001):
        z = rng.choice(zaehler)
        stand = round(rng.uniform(0, 90000), 1)
        if _some(rng, 0.015):
            stand = -stand
        eh = einheit[z[2].lower()]
        if _some(rng, 0.03):
            eh = rng.choice(["kWh", "m3", "KWH", ""])  # Einheit passt nicht zur Sparte
        ablesungen.append((i, z[0], _day(rng, 1500, 60 if _some(rng, 0.02) else 0), None if _some(rng, 0.02) else stand,
                           rng.choice(["Turnus"] * 6 + ["Kunde"] * 3 + ["Schaetzung"] * 2 + ["turnus"]), eh))
    _load(con, "ablesung", ablesungen)


STADTWERKE_OPS = [
    {"aktion": "tabelle_beschreiben", "tabelle": "zaehler", "beschreibung": "Alle Messgeraete im Netzgebiet.",
     "owner": "Messstellenbetrieb", "steward": "Zaehlerwesen"},
    {"aktion": "spalte_dokumentieren", "tabelle": "zaehler", "spalte": "sparte", "bedeutung": "Was der Zaehler misst",
     "erlaubte_werte": ["Strom", "Gas", "Wasser", "Waerme"]},
    {"aktion": "spalte_dokumentieren", "tabelle": "zaehler", "spalte": "eichung_gueltig_bis",
     "bedeutung": "Ende der Eichfrist, danach muss der Zaehler getauscht werden"},
    {"aktion": "regel_vorschlagen", "tabelle": "zaehler", "check": "sparte IN ('Strom', 'Gas', 'Wasser', 'Waerme')",
     "begruendung": "Einheitliche Schreibweise der Sparte"},
    {"aktion": "regel_entscheiden", "tabelle": "zaehler", "regel": "sparte IN ('Strom', 'Gas', 'Wasser', 'Waerme')", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "zaehler", "check": "eichung_gueltig_bis > einbau_am",
     "begruendung": "Die Eichfrist endet nach dem Einbau"},
    {"aktion": "regel_entscheiden", "tabelle": "zaehler", "regel": "eichung_gueltig_bis > einbau_am", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "zaehler", "check": "status <> 'aktiv' OR eichung_gueltig_bis >= DATE '2025-12-31'",
     "begruendung": "Aktive Zaehler brauchen eine gueltige Eichung"},
    {"aktion": "frage_stellen", "tabelle": "zaehler", "spalte": "ortsteil",
     "frage": "Bei einigen Zaehlern ist der Ortsteil leer. Sind das Zaehler ausserhalb des Stadtgebiets?"},
    {"aktion": "tabelle_beschreiben", "tabelle": "vertrag", "beschreibung": "Liefervertraege je Zaehler.", "owner": "Kundenservice"},
    {"aktion": "spalte_dokumentieren", "tabelle": "vertrag", "spalte": "ende", "bedeutung": "Vertragsende",
     "hinweise": "Leer bedeutet: Vertrag laeuft unbefristet."},
    {"aktion": "regel_vorschlagen", "tabelle": "vertrag", "check": "ende >= beginn", "begruendung": "Ende nie vor Beginn"},
    {"aktion": "regel_entscheiden", "tabelle": "vertrag", "regel": "ende >= beginn", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "vertrag", "check": "abschlag > 0", "begruendung": "Jeder Vertrag hat einen Abschlag"},
    {"aktion": "regel_entscheiden", "tabelle": "vertrag", "regel": "abschlag > 0", "status": "abgelehnt",
     "begruendung": "Kunden mit Jahresrechnung zahlen keinen Abschlag, dort steht 0. Negativ ist aber immer falsch."},
    {"aktion": "regel_vorschlagen", "tabelle": "vertrag", "check": "abschlag >= 0", "begruendung": "Negative Abschlaege gibt es nicht"},
    {"aktion": "regel_entscheiden", "tabelle": "vertrag", "regel": "abschlag >= 0", "status": "akzeptiert"},
    {"aktion": "tabelle_beschreiben", "tabelle": "ablesung", "beschreibung": "Jeder erfasste Zaehlerstand.", "owner": "Abrechnung"},
    {"aktion": "spalte_dokumentieren", "tabelle": "ablesung", "spalte": "art", "bedeutung": "Wie der Stand zustande kam",
     "erlaubte_werte": ["Turnus", "Kunde", "Schaetzung"]},
    {"aktion": "regel_vorschlagen", "tabelle": "ablesung", "check": "stand >= 0", "begruendung": "Zaehlerstaende sind nicht negativ"},
    {"aktion": "regel_entscheiden", "tabelle": "ablesung", "regel": "stand >= 0", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "ablesung", "check": "datum <= DATE '2025-12-31'",
     "begruendung": "Ablesungen liegen nicht in der Zukunft"},
    {"aktion": "regel_entscheiden", "tabelle": "ablesung", "regel": "datum <= DATE '2025-12-31'", "status": "akzeptiert"},
    {"aktion": "regel_vorschlagen", "tabelle": "ablesung", "check": "einheit IN ('kWh', 'm3')", "begruendung": "Nur zwei Einheiten sind zulaessig"},
    {"aktion": "wissen_festhalten", "tabelle": "ablesung", "von": "Abrechnung",
     "text": "Geschaetzte Staende entstehen, wenn der Kunde zum Stichtag nichts gemeldet hat. Sie werden bei der naechsten echten Ablesung korrigiert."},
]


DEMOS: dict[str, tuple[str, Callable[[Any, random.Random], None], list[dict[str, Any]], list[str]]] = {
    "shop": ("Demo: Onlineshop", _shop, SHOP_OPS, ["kunde", "produkt", "bestellung", "bestellposition"]),
    "vermietung": ("Demo: Baumaschinen-Vermietung", _vermietung, VERMIETUNG_OPS, ["geraet", "mietvertrag", "wartung"]),
    "stadtwerke": ("Demo: Stadtwerke", _stadtwerke, STADTWERKE_OPS, ["zaehler", "vertrag", "ablesung"]),
}


def build(name: str, seed: int = 42) -> Path:
    """Erzeugt Datenbank, Doku-Dateien, Regelergebnisse und HTML-Report einer Demo. Gibt den Report zurueck."""
    import duckdb

    if name not in DEMOS:
        raise ValueError(f"Unbekannte Demo {name!r}. Es gibt: {', '.join(DEMOS)}")
    title, make, ops, tables = DEMOS[name]
    root = demo_root()
    root.mkdir(parents=True, exist_ok=True)
    db = root / f"{name}.duckdb"
    if db.exists():
        db.unlink()
    data = root / name
    for sub in ("tables", "profiles", "reports"):
        for old in (data / sub).glob("*") if (data / sub).exists() else []:
            old.unlink()
    con = duckdb.connect(str(db))
    try:
        make(con, random.Random(seed))
    finally:
        con.close()

    previous = os.environ.get("SQLPROFIL_DEMO")
    os.environ["SQLPROFIL_DEMO"] = name
    try:
        for t in tables:
            profiler.profile_table(t)
        patch.apply_ops(ops)
        for t in tables:
            rules.run_rules(t)
        return htmlreport.write_html(tables, title=title)
    finally:
        if previous is None:
            os.environ.pop("SQLPROFIL_DEMO", None)
        else:
            os.environ["SQLPROFIL_DEMO"] = previous
