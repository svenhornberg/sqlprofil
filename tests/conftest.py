import os

import pytest

SETUP_SQL = """
CREATE TABLE auftrag (
    id INTEGER PRIMARY KEY,
    kunde_name VARCHAR,
    status VARCHAR,
    beginn DATE,
    ende DATE,
    betrag DECIMAL(10,2),
    storniert BOOLEAN
);
INSERT INTO auftrag VALUES
 (1, 'Alpha GmbH', 'offen',   DATE '2024-01-01', DATE '2024-02-01', 100.00, false),
 (2, 'Beta AG',    'aktiv',   DATE '2024-03-01', NULL,              250.50, false),
 (3, 'Gamma KG',   'beendet', DATE '2024-05-01', DATE '2024-04-01', -20.00, false),
 (4, 'Delta OHG',  'X',       DATE '2024-06-01', DATE '2024-07-01', 0.00,   true),
 (5, 'Alpha GmbH', ' aktiv',  NULL,              NULL,              NULL,   NULL),
 (6, 'Epsilon',    '',        DATE '2024-08-01', DATE '2024-09-01', 75.00,  false);
"""


@pytest.fixture
def duck(tmp_path, monkeypatch):
    """Eine DuckDB-Datei mit einer kleinen Tabelle voller typischer Datenfehler."""
    duckdb = pytest.importorskip("duckdb")
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    con.execute(SETUP_SQL)
    con.close()
    for key in list(os.environ):
        if key.startswith("SQLPROFIL_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("SQLPROFIL_DIALECT", "duckdb")
    monkeypatch.setenv("SQLPROFIL_DSN", str(db))
    monkeypatch.setenv("SQLPROFIL_DATA_DIR", str(tmp_path))
    return tmp_path
