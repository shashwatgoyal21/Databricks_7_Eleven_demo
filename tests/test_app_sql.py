"""Every SQL statement the app sends to the warehouse must only use tables and columns the build job
actually writes. Catches the 'column cannot be resolved' class of error before deploy."""

import importlib
import re
from pathlib import Path

import pandas as pd
import pytest
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify

ROOT = Path(__file__).resolve().parents[1]
# Created outside the build job's DataFrames: the endpoint's inference table (written by AI Gateway).
EXTERNAL_TABLES = {"nbo_decision_payload"}


@pytest.fixture()
def captured_sql(monkeypatch):
    monkeypatch.delenv("NBO_LOCAL_DATA", raising=False)
    monkeypatch.setenv("NBO_SCHEMA", "nbo_demo")
    import data
    data = importlib.reload(data)
    data.clear_cache()
    seen = []

    def fake_query(sql_text, params=None):
        seen.append((sql_text, params or {}))
        return pd.DataFrame({"member_id": [1], "event_ts": ["2026-09-30 07:00:00"], "n": [0]})

    monkeypatch.setattr(data, "_query", fake_query)
    data.table("promotions")
    data.stores_by_traffic()
    data.store_feed(1001)
    data.event_bundle(42)
    data.table_counts(("instore_events", "member_offer_scores"))
    data.log_decisions([{"event_id": 1, "store_id": 1001, "member_id": 7, "decision": "Offer served",
                         "promotion_id": "PR01", "channel": "push", "latency_ms": 12.0}])
    return seen


def _schema_for_sqlglot(table_schemas):
    return {"nbo_demo": {t: {c: "STRING" for c in cols} for t, cols in table_schemas.items()}}


def test_app_sends_sql(captured_sql):
    assert len(captured_sql) >= 8


def test_every_select_resolves_against_built_tables(captured_sql, table_schemas):
    schema = _schema_for_sqlglot(table_schemas)
    for sql_text, _ in captured_sql:
        tree = sqlglot.parse_one(sql_text, read="databricks")
        if isinstance(tree, exp.Insert):
            continue
        for t in tree.find_all(exp.Table):
            assert t.name in table_schemas, f"App reads table {t.name}, which the build job does not create"
        try:
            qualify(tree, schema=schema, dialect="databricks", validate_qualify_columns=True)
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"{e}\nin query:\n{sql_text}")


def test_insert_into_decision_log_matches_ddl(captured_sql, table_schemas):
    inserts = [s for s, _ in captured_sql if s.lstrip().upper().startswith("INSERT")]
    assert inserts, "log_decisions sent no INSERT"
    for sql_text in inserts:
        tree = sqlglot.parse_one(sql_text, read="databricks")
        target = tree.this
        cols = [c.name for c in target.expressions]
        table = target.this.name
        missing = set(cols) - set(table_schemas[table])
        assert not missing, f"INSERT INTO {table} names columns the table does not have: {missing}"


def test_query_parameters_are_all_bound(captured_sql):
    for sql_text, params in captured_sql:
        names = set(re.findall(r"(?<!:):([A-Za-z_]\w*)", sql_text))
        assert names <= set(params), f"Unbound parameters {names - set(params)} in:\n{sql_text}"


def test_tables_named_in_app_exist(table_schemas):
    src = (ROOT / "app" / "app.py").read_text()
    used = set(re.findall(r'data\.table\("(\w+)"\)', src))
    used |= set(re.findall(r'\("(\w+)", "(?:Bronze|Silver[^"]*|Gold)"', src))
    missing = used - set(table_schemas) - EXTERNAL_TABLES
    assert not missing, f"app.py reads tables the build job does not create: {missing}"


def test_profile_columns_exist(table_schemas):
    import data
    missing = set(data.PROFILE_COLS) - set(table_schemas["member_profile"])
    assert not missing, f"PROFILE_COLS not in member_profile: {missing}"
