# sqlprofil für Sprachmodelle

Diese Datei erklärt das Repo einem Sprachmodell, das Fragen dazu beantworten oder daran arbeiten soll.
Menschen lesen besser `README.md`. Regeln für die Weiterentwicklung stehen in `CLAUDE.md`.

## Zweck in einem Absatz

sqlprofil macht aus "die Datenqualität ist schlecht" pro Tabelle drei abarbeitbare Dinge: Fakten
(Kennzahlen pro Spalte, reines SQL), Regeln (boolesche Ausdrücke pro Zeile mit Status) und Wissen
(Erklärungen der Fachabteilung). Ein Sprachmodell schlägt Regeln und Rückfragen vor und führt den Chat.
Es rechnet keine Kennzahlen und sieht keine Rohzeilen. Das Repo ist ein neutrales, herstellerunabhängiges
Werkzeug mit Demo-Daten und enthält keine Daten oder Bezüge zu einer bestimmten Organisation.

## Begriffe

| Begriff | Bedeutung |
|---|---|
| Profil | Kennzahlen einer Tabelle aus einem Lauf, JSON, jederzeit neu erzeugbar |
| Doku-Datei | `tables/<schema>.<tabelle>.yaml`, die einzige Quelle für Wissen und Regeln, von Hand pflegbar |
| Regel | Ausdruck, der für jede Zeile wahr sein soll; Status `vorgeschlagen`, `akzeptiert`, `abgelehnt` |
| Verstoß | Zeile, für die der Ausdruck falsch ist. Ergibt er `NULL`, ist es kein Verstoß |
| Offene Frage | Rückfrage an die Fachabteilung; die Antwort wird zu Wissen |
| Patch | YAML-Liste von Aktionen auf Doku-Dateien, entsteht im Chat, wird mit `sqlprofil patch` eingespielt |
| Dialekt | Datenbanktyp: `mssql`, `postgres`, `duckdb` |
| Datenverzeichnis | `SQLPROFIL_DATA_DIR`, Standard `./daten`, nicht Teil dieses Repos |

## Aufbau

```
sqlprofil/
  config.py       Einstellungen aus Umgebung und .env; Demo-Modus übersteuert Datenbank und Datenverzeichnis
  dialects.py     alles Datenbankspezifische: Quotierung, Typnamen, Stichprobe, Verbindung (schreibgeschützt)
  sqlguard.py     lässt nur eine einzelne SELECT-Anweisung bzw. einen Regelausdruck durch
  profiler.py     baut eine Aggregat-Abfrage pro Tabelle, schreibt das Profil
  store.py        liest und schreibt Doku-Dateien; verhindert doppelte Regeln und Fragen
  rules.py        zählt Verstöße je Regel
  report.py       Markdown-Report; ruft das Modell über LiteLLM auf und übernimmt dessen Vorschläge
  htmlreport.py   HTML-Report als einzelne Datei für eine, mehrere oder alle Tabellen
  patch.py        Patch prüfen, beschreiben, ausgeben, einlesen, einspielen; Eingang unter patches/
  demo.py         erfundene Daten für drei Branchen samt Doku, Regeln und Report
  cli.py          Kommandozeile
agents/sqlprofil_agent/agent.py   Chat-Agent (Google ADK), Werkzeuge rufen die Module oben auf
tests/            laufen gegen DuckDB, ohne Server und ohne Modell
```

## Datenfluss

1. `profile`: Spalten aus `INFORMATION_SCHEMA` lesen, eine Aggregat-Abfrage ausführen, für Spalten mit
   wenigen verschiedenen Werten die häufigsten Werte holen, Profil schreiben, fehlende Spalten in der
   Doku-Datei anlegen.
2. `check`: jede akzeptierte Regel als `SUM(CASE WHEN NOT (<ausdruck>) THEN 1 ELSE 0 END)` zählen.
3. `report`: Profil, Doku-Datei und Regelergebnisse ans Modell geben. Antwort ist JSON mit
   `einschaetzung`, `regelvorschlaege`, `fragen`. Jeder Vorschlag wird geprüft und gegen die Datenbank
   getestet, bevor er mit Status `vorgeschlagen` in die Doku-Datei kommt.
4. Mensch entscheidet: `rule` (akzeptieren, ablehnen mit Begründung), `answer` (Frage beantworten).
5. `html`: aus den Dateien im Datenverzeichnis eine HTML-Seite bauen. Kein Modellaufruf.

Im Chat laufen dieselben Schritte über Werkzeuge. Im Modus `patch` werden Änderungen nur vorgemerkt
(im Sitzungszustand) und am Ende als Patch ausgegeben; im Modus `direkt` sofort geschrieben.

## Kommandozeile

```
sqlprofil [--demo NAME] <befehl>
  demo [NAME ...]                   Demo-Daten erzeugen: shop, rental, utilities
  tables                            Tabellen der Datenbank
  profile TABELLE [--sample P]      Profil berechnen
  check TABELLE                     akzeptierte Regeln ausführen
  report TABELLE [--no-llm]         Markdown-Report
  run TABELLE [--sample P] [--no-llm]   profile + check + report
  html [TABELLE ...] [--all] [--with-views] [--refresh] [--sample P] [--title T] [-o DATEI]
  rule TABELLE ID accepted|rejected|proposed [--reason TEXT]
  answer TABELLE ID TEXT [--by NAME]
  patch [DATEI|-] [--dry-run]       ohne Datei: Eingang auflisten
```

Tabellen werden als `schema.tabelle` angegeben; ohne Schema gilt das Standardschema des Dialekts
(`dbo`, `public`, `main`).

## Patch-Format

```yaml
# sqlprofil-patch v1
- aktion: spalte_dokumentieren      # Pflicht: tabelle, spalte. Optional: bedeutung, hinweise, erlaubte_werte, pii
- aktion: tabelle_beschreiben       # Pflicht: tabelle. Optional: beschreibung, owner, steward
- aktion: wissen_festhalten         # Pflicht: tabelle, text. Optional: von
- aktion: frage_stellen             # Pflicht: tabelle, frage. Optional: spalte
- aktion: frage_beantworten         # Pflicht: tabelle, frage (ID oder Wortlaut), antwort. Optional: von
- aktion: regel_vorschlagen         # Pflicht: tabelle, check. Optional: begruendung
- aktion: regel_entscheiden         # Pflicht: tabelle, regel (ID oder Ausdruck), status. Optional: begruendung
```

Ein Patch wird vollständig geprüft, bevor die erste Aktion läuft. Unbekannte Aktionen oder Felder
führen zur Ablehnung des ganzen Patches.

## Zusicherungen, auf die man sich verlassen kann

- sqlprofil schreibt nie in die untersuchte Datenbank. PostgreSQL und DuckDB werden schreibgeschützt
  geöffnet, zusätzlich filtert `sqlguard.py`. Für SQL Server braucht es einen Benutzer mit reinen Leserechten.
- Das Modell bekommt Kennzahlen, nie Zeilen. Ausnahme: `SQLPROFIL_CHAT_SQL=on`.
- Einzelwerte personenbezogen wirkender Spalten (Namensmuster oder `pii: true`) erscheinen in keinem
  Profil und keinem Report.
- Zahlen in Reports stammen aus dem Profil, nicht vom Modell. Nur der Abschnitt "Einschätzung" ist Modelltext.
- Eine Regel mit gleichem Ausdruck wird nie doppelt angelegt, auch nicht nach einer Ablehnung.
- Alle Werte aus der Datenbank werden im HTML escaped. Die HTML-Datei lädt nichts aus dem Netz.

## Was nicht belegt ist

- Gegen einen echten SQL Server lief der Code noch nicht. Getestet sind die erzeugten Abfragen und der
  Connection String.
- Regelvorschläge und Chatverhalten hängen vom gewählten Modell ab und sind nicht automatisiert getestet.
- Unter SQL Server ist die Anzahl verschiedener Werte geschätzt (`APPROX_COUNT_DISTINCT`), in den Reports
  mit "ca." gekennzeichnet.
- Regeln prüfen einzelne Zeilen. Dubletten, verwaiste Fremdschlüssel und Abgleiche zwischen Tabellen
  deckt das Regelformat nicht ab.
