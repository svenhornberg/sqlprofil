# sqlprofil

Datenqualität pro Tabelle: Kennzahlen berechnen, Regeln vorschlagen und prüfen, das Wissen der
Fachabteilung festhalten und alles als Report oder im Chat zeigen.

Für **SQL Server** (Windows-Authentifizierung), **PostgreSQL** und **DuckDB**. Der Chat läuft mit dem
[Google Agent Development Kit](https://google.github.io/adk-docs/), das Modell ist über
[LiteLLM](https://docs.litellm.ai/) frei wählbar.

## Die Idee

"Die Datenqualität ist schlecht" ist keine Aussage, mit der man arbeiten kann. sqlprofil macht daraus
pro Tabelle drei Dinge, die man abarbeiten kann:

1. **Fakten.** Leerwerte, Wertebereiche, häufigste Werte, Ausreißer. Reines SQL, keine KI, ein Tabellenscan.
2. **Regeln.** Ausdrücke, die für jede Zeile gelten sollen (`mietende >= mietbeginn`). Ein Modell schlägt
   sie vor, ein Mensch akzeptiert sie oder lehnt sie ab. Akzeptierte Regeln laufen bei jedem Lauf mit.
3. **Wissen.** Was eine Spalte bedeutet, warum ein Wert leer sein darf, welche Altlasten es gibt.
   Das steht in einer YAML-Datei pro Tabelle und gehört in Git.

Eine abgelehnte Regel bleibt mit Begründung in der Datei. Damit wird sie nicht wieder vorgeschlagen,
und die Begründung ist oft genau das Wissen, das vorher nur in Köpfen war.

## In fünf Minuten ausprobieren

Der Demo-Modus braucht weder eine Datenbank noch ein Modell. Er erzeugt erfundene Daten aus drei
Branchen, jeweils mit absichtlich eingebauten Fehlern:

| Demo | Tabellen |
|---|---|
| `shop` | Onlineshop: kunde, produkt, bestellung, bestellposition |
| `vermietung` | Baumaschinen-Vermietung: geraet, mietvertrag, wartung |
| `stadtwerke` | Stadtwerke: zaehler, vertrag, ablesung |

```
python -m venv .venv
.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
pip install -e ".[all]"
sqlprofil demo
```

Danach liegt unter `demo/<name>/reports/index.html` je ein fertiger Report. Alle weiteren Befehle
arbeiten mit `--demo <name>` auf diesen Daten:

```
sqlprofil --demo vermietung tabellen
sqlprofil --demo vermietung pruefen mietvertrag
```

## Eigene Datenbank

`.env.example` nach `.env` kopieren und anpassen.

**SQL Server.** Angemeldet wird mit dem Windows-Benutzer, der das Programm startet, ein Passwort steht
nirgends. Der Treiber `mssql-python` bringt alles Nötige mit, eine ODBC-Installation mit
Administratorrechten ist nicht erforderlich. Das funktioniert unter Windows direkt, unter Linux und
WSL nur mit eingerichtetem Kerberos.

```
SQLPROFIL_DIALECT=mssql
MSSQL_SERVER=sqlserver01.example.local
MSSQL_DATABASE=MeineDB
```

**PostgreSQL.** Es gelten die üblichen Variablen `PGHOST`, `PGDATABASE`, `PGUSER` oder ein
`SQLPROFIL_DSN`. Die Sitzung wird von der Datenbank selbst schreibgeschützt geöffnet.

**DuckDB.** Entweder eine `.duckdb`-Datei oder `:memory:` mit einem Init-Skript
(`SQLPROFIL_DUCKDB_INIT`), das Views auf Parquet-, CSV- oder SQLite-Dateien anlegt. So lässt sich
fast jede Datenquelle profilieren.

## Befehle

```
sqlprofil tabellen                       Tabellen der Datenbank
sqlprofil profil dbo.auftrag             Kennzahlen berechnen, Doku-Datei anlegen
sqlprofil pruefen dbo.auftrag            akzeptierte Regeln ausführen
sqlprofil report dbo.auftrag             Markdown-Report, Modell schlägt Regeln und Fragen vor
sqlprofil report dbo.auftrag --ohne-ki   nur Fakten
sqlprofil alles dbo.auftrag              profil + pruefen + report

sqlprofil html dbo.auftrag               HTML-Report für eine Tabelle
sqlprofil html dbo.auftrag dbo.kunde     für eine Auswahl
sqlprofil html                           für alle Tabellen mit Doku-Datei
sqlprofil html --alle                    für die ganze Datenbank (--mit-views, --stichprobe 10)

sqlprofil regel dbo.auftrag r3 abgelehnt --grund "Gutschriften sind negativ"
sqlprofil antwort dbo.auftrag f1 "Laufende Aufträge haben kein Ende." --von Fachbereich
sqlprofil patch vorschlag.yaml --pruefen
```

Der HTML-Report ist eine einzelne Datei ohne externe Abhängigkeiten und lässt sich per Mail oder
Dateifreigabe weitergeben. Bei großen Tabellen liest `--stichprobe 10` nur etwa zehn Prozent.

## Wo die Ergebnisse liegen

```
daten/
  tables/dbo.auftrag.yaml        Wissen, Spaltenerklärungen, Regeln, offene Fragen (von Hand pflegbar)
  profiles/dbo.auftrag.json      Kennzahlen des letzten Laufs
  reports/dbo.auftrag.md|html    Reports
```

`daten/` steht in `.gitignore`: Erkenntnisse über eine echte Datenbank gehören nicht in dieses Repo.
Leg dafür ein eigenes, privates Repo an und zeig mit `SQLPROFIL_DATA_DIR` darauf.

So sieht eine Tabellen-Datei aus:

```yaml
tabelle: dbo.mietvertrag
beschreibung: Eine Zeile pro Mietvorgang eines Geräts.
owner: Vertriebsinnendienst
spalten:
  mietende:
    bedeutung: Vereinbartes Ende laut Vertrag
    hinweise: Die tatsächliche Rückgabe steht in rueckgabe_am.
    pii: false
regeln:
- id: r1
  check: mietende >= mietbeginn
  status: akzeptiert
- id: r4
  check: tagespreis > 0
  status: abgelehnt
  begruendung: Ersatzgeräte bei Ausfall werden kostenlos gestellt und mit 0 geführt.
offene_fragen:
- id: f1
  spalte: rueckgabe_am
  frage: Bei manchen beendeten Verträgen fehlt das Rückgabedatum. Wird die Rückgabe dort nicht gebucht?
```

Eine Regel ist ein Ausdruck, der für jede Zeile wahr sein soll. Ergibt er `NULL`, zählt die Zeile
nicht als Verstoß. Wer Leerwerte verbieten will, schreibt `ende IS NOT NULL AND ende >= beginn`.

## Chat für Fachanwender

```
adk web agents
```

Im Browser `sqlprofil_agent` wählen. Der Agent liest Profil und Dokumentation, erklärt Auffälligkeiten,
zählt Verstöße gegen eine Regel und nimmt auf, was die Fachabteilung erklärt. Zum Ausprobieren ohne
eigene Datenbank: `SQLPROFIL_DEMO=vermietung` setzen. Ein Modell braucht der Chat immer
(`SQLPROFIL_MODEL`, zum Beispiel `azure/gpt-4.1` oder ein lokales `ollama_chat/...`).

Es gibt zwei Betriebsarten (`SQLPROFIL_CHAT_MODE`):

- **`patch` (Standard).** Der Chat ändert keine Dateien. Er sammelt die Änderungen und gibt sie am Ende
  als lesbaren Patch aus. Den kopiert die Fachanwenderin und schickt ihn an die Person, die das Repo pflegt.
- **`direkt`.** Änderungen landen sofort in `tables/*.yaml`. Sinnvoll, wenn du selbst chattest.

Ein Patch ist bewusst kein `diff`, sondern eine kurze Liste von Aktionen mit einer Zusammenfassung
in Klartext. Er übersteht Kopieren aus Chat und Mail:

```yaml
# sqlprofil-patch v1
# Datum: 2026-01-15, von: Disposition
# Was sich aendert:
#  1. dbo.geraet.status dokumentieren (bedeutung: Wo die Maschine gerade ist)
#  2. dbo.geraet: Regel r4 auf abgelehnt setzen (Vorführgeräte haben keine Prüfung)

- aktion: spalte_dokumentieren
  tabelle: dbo.geraet
  spalte: status
  bedeutung: Wo die Maschine gerade ist
- aktion: regel_entscheiden
  tabelle: dbo.geraet
  regel: r4
  status: abgelehnt
  begruendung: Vorführgeräte haben keine Prüfung
```

Einspielen:

```
sqlprofil patch vorschlag.yaml --pruefen     zeigt, was passieren würde
sqlprofil patch vorschlag.yaml               spielt ein
git diff                                     im Datenverzeichnis: was sich an den Dateien geändert hat
```

Ein Patch wird ganz oder gar nicht eingespielt. Erlaubte Aktionen: `tabelle_beschreiben`,
`spalte_dokumentieren`, `wissen_festhalten`, `frage_stellen`, `frage_beantworten`, `regel_vorschlagen`,
`regel_entscheiden`.

## Was das Modell sieht

- Kennzahlen, die Doku-Datei und Regelergebnisse. Keine Rohzeilen.
- Häufigste Werte nur bei Spalten mit höchstens 50 verschiedenen Werten.
- Bei Spalten, deren Name nach Personenbezug aussieht (name, mail, telefon, iban, geburt ...), gar
  keine Einzelwerte. Mit `pii: true` in der Doku-Datei lässt sich das für jede Spalte erzwingen,
  mit `pii: nein` für harmlose Treffer wie `produktname` aufheben.
- Freie SQL-Abfragen im Chat sind ausgeschaltet. `SQLPROFIL_CHAT_SQL=on` schaltet sie ein, dann
  können einzelne Datensätze ans Modell gehen.

## Sicherheit

sqlprofil schreibt nie in die Datenbank. Dafür sorgen zwei Schichten, und die erste ist deine Aufgabe:

1. Ein Datenbankbenutzer, der nur lesen darf (SQL Server: `db_datareader`). Am besten gegen eine
   lesbare Replika, die Verbindung setzt dafür `ApplicationIntent=ReadOnly`.
2. Ein Filter, der nur eine einzelne `SELECT`-Anweisung durchlässt und Regeln auf einen Ausdruck
   ohne Semikolon, Kommentar und Dateizugriff beschränkt. PostgreSQL und DuckDB öffnen die Sitzung
   zusätzlich schreibgeschützt.

Der Filter ist eine Absicherung, kein Ersatz für die Rechte des Benutzers.

## Entwicklung

```
pip install -e ".[all,dev]"
pytest
```

Die Tests laufen gegen DuckDB und brauchen weder Server noch Modell. Der Ablauf wurde zusätzlich gegen
PostgreSQL 16 geprüft. Für SQL Server sind die erzeugten Abfragen getestet, ein Lauf gegen einen echten
Server steht noch aus.

Ein weiterer Dialekt ist eine Klasse in `sqlprofil/dialects.py`: Quotierung, Typnamen, Verbindung.
