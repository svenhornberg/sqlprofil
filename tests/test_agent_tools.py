"""Die Werkzeuge des Chat-Agenten, ohne Modell aufgerufen."""
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("google.adk")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))


def _agent(monkeypatch, mode, chat_sql="off"):
    monkeypatch.setenv("SQLPROFIL_CHAT_MODE", mode)
    monkeypatch.setenv("SQLPROFIL_CHAT_SQL", chat_sql)
    import sqlprofil_agent.agent as mod
    return importlib.reload(mod)


def test_patch_modus_schreibt_nichts(duck, monkeypatch):
    from sqlprofil import patch, profiler, store
    profiler.profile_table("auftrag")
    before = store.path_for("auftrag").read_text(encoding="utf-8")
    a = _agent(monkeypatch, "patch")
    ctx = SimpleNamespace(state={})
    names = {t.__name__ for t in a.root_agent.tools}
    assert "patch_ausgeben" in names and "sql_abfragen" not in names

    assert a.regel_testen("auftrag", "ende >= beginn")["verstoesse"] == 1
    r = a.regel_vorschlagen("auftrag", "ende >= beginn", "Ende nie vor Beginn", ctx)
    assert r["status"] == "vorgemerkt" and r["verstoesse_aktuell"] == 1
    a.regel_entscheiden("auftrag", "ende >= beginn", "akzeptiert", "", ctx)
    a.spalte_dokumentieren("auftrag", "status", ctx, bedeutung="Bearbeitungsstand", erlaubte_werte=["offen", "aktiv"])
    a.wissen_festhalten("auftrag", "Laufende Auftraege haben kein Ende.", ctx, von="Fachbereich")
    assert a.regel_vorschlagen("auftrag", "gibt_es_nicht > 0", "x", ctx)["status"] == "fehler"
    assert a.regel_vorschlagen("auftrag", "1=1; DROP TABLE auftrag", "x", ctx)["status"] == "fehler"
    assert len(a.tabelle_lesen("auftrag", ctx)["in_diesem_chat_vorgemerkt"]) == 4
    assert store.path_for("auftrag").read_text(encoding="utf-8") == before  # nichts gespeichert

    out = a.patch_ausgeben(ctx, von="Fachbereich")
    assert out["anzahl"] == 4
    patch.apply_ops(patch.parse(out["patch"]))  # der kopierte Text laesst sich einspielen
    doc = store.load("auftrag")
    assert doc["regeln"][0]["status"] == "akzeptiert" and doc["spalten"]["status"]["bedeutung"] == "Bearbeitungsstand"


def test_direkt_modus_und_sql(duck, monkeypatch):
    from sqlprofil import profiler, store
    profiler.profile_table("auftrag")
    a = _agent(monkeypatch, "direkt", chat_sql="on")
    ctx = SimpleNamespace(state={})
    assert a.spalte_dokumentieren("auftrag", "status", ctx, bedeutung="Bearbeitungsstand")["status"] == "gespeichert"
    assert store.load("auftrag")["spalten"]["status"]["bedeutung"] == "Bearbeitungsstand"
    res = a.sql_abfragen("SELECT status, COUNT(*) AS n FROM auftrag GROUP BY status ORDER BY status")
    assert res["status"] == "ok" and res["spalten"] == ["status", "n"]
    assert a.sql_abfragen("DELETE FROM auftrag")["status"] == "fehler"
    assert a.sql_abfragen("SELECT * FROM read_csv('/etc/passwd')")["status"] == "fehler"
