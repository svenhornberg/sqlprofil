import pytest

from sqlprofil.sqlguard import UnsafeSql, assert_check_expression, assert_readonly_select, split_table


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select a, 'drop table x' from t where b like '%;%'",
    "WITH x AS (SELECT 1 AS a) SELECT * FROM x",
    "SELECT [update] FROM t",
    'SELECT "delete" FROM t',
    "SELECT 1;",
])
def test_select_erlaubt(sql):
    assert_readonly_select(sql)


@pytest.mark.parametrize("sql", [
    "",
    "DELETE FROM t",
    "SELECT 1; DROP TABLE t",
    "SELECT * INTO neu FROM t",
    "EXEC sp_who",
    "WITH x AS (SELECT 1) DELETE FROM t",
    "SELECT * FROM OPENROWSET('x','y','z')",
    "SELECT pg_read_file('/etc/passwd')",
    "COPY t TO '/tmp/x'",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM '/etc/passwd'",
    "SELECT * FROM t JOIN 'x.parquet' USING (id)",
    "SELECT $$x$$",
    "SELECT /* */ 1 /* ; */ ; UPDATE t SET a = 1",
])
def test_rest_verboten(sql):
    with pytest.raises(UnsafeSql):
        assert_readonly_select(sql)


@pytest.mark.parametrize("expr", ["ende >= beginn", "status IN ('offen', 'aktiv')", "(betrag >= 0) AND betrag < 1e6",
                                  "ende IS NOT NULL AND ende >= beginn", "LEN([name]) > 0"])
def test_regel_erlaubt(expr):
    assert assert_check_expression(expr) == expr


@pytest.mark.parametrize("expr", ["", "1=1; DROP TABLE t", "1=1) OR (1=1", "a > 0 -- x", "a > 0 /* x */",
                                  "a IN (SELECT a FROM read_csv('x'))", "(a > 0", "EXISTS (SELECT 1 FROM 'x.csv')"])
def test_regel_verboten(expr):
    with pytest.raises(UnsafeSql):
        assert_check_expression(expr)


def test_split_table():
    assert split_table("kunde", "dbo") == ("dbo", "kunde")
    assert split_table("[verkauf].[kunde]", "dbo") == ("verkauf", "kunde")
    assert split_table('"public"."kunde"', "public") == ("public", "kunde")
    with pytest.raises(UnsafeSql):
        split_table("a.b.c", "dbo")
