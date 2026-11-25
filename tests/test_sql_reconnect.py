"""The app caches one warehouse connection. After a long idle it goes stale; a read must reconnect and retry
once, and a write must never run twice."""

import functools

import pyarrow as pa
import pytest
from databricks.sql.exc import RequestError, ServerOperationError

import data


class Cursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        if self.conn.fail_on_execute:
            raise self.conn.fail_on_execute

    def fetchall_arrow(self):
        return pa.table({"n": [1]})


class Conn:
    def __init__(self, fail_on_execute=None, fail_on_cursor=None):
        self.fail_on_execute, self.fail_on_cursor = fail_on_execute, fail_on_cursor
        self.executed, self.closed = [], False

    def cursor(self):
        if self.fail_on_cursor:
            raise self.fail_on_cursor
        return Cursor(self)

    def close(self):
        self.closed = True


@pytest.fixture
def connections(monkeypatch):
    """Hand out the given connections one at a time, like reconnecting after the cache is cleared."""
    def install(*conns):
        it = iter(conns)

        @functools.cache
        def fake():
            return next(it)

        monkeypatch.setattr(data, "_connection", fake)
    return install


STALE = RequestError("Error during request to server")


def test_read_reconnects_after_stale_connection(connections):
    stale, fresh = Conn(fail_on_execute=STALE), Conn()
    connections(stale, fresh)
    out = data._query("SELECT 1")
    assert out.n.tolist() == [1]
    assert stale.closed and fresh.executed == ["SELECT 1"]


def test_read_gives_up_after_one_retry(connections):
    connections(Conn(fail_on_execute=STALE), Conn(fail_on_execute=STALE))
    with pytest.raises(RequestError):
        data._query("SELECT 1")


def test_write_is_not_retried_after_it_was_sent(connections):
    first = Conn(fail_on_execute=STALE)
    connections(first, Conn())
    with pytest.raises(RequestError):
        data._query("INSERT INTO t VALUES (1)")
    assert first.executed == ["INSERT INTO t VALUES (1)"]


def test_write_is_retried_if_the_connection_failed_before_sending(connections):
    stale, fresh = Conn(fail_on_cursor=STALE), Conn()
    connections(stale, fresh)
    data._query("UPDATE t SET a = 1")
    assert fresh.executed == ["UPDATE t SET a = 1"]


def test_sql_errors_are_not_retried(connections):
    first = Conn(fail_on_execute=ServerOperationError("[PARSE_SYNTAX_ERROR] bad sql"))
    connections(first, Conn())
    with pytest.raises(ServerOperationError):
        data._query("SELECT nope")
    assert first.executed == ["SELECT nope"]
