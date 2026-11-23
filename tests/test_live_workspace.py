"""Checks against the real workspace after the build job runs. Skipped unless credentials are set:

    DATABRICKS_HOST=... DATABRICKS_TOKEN=... NBO_WAREHOUSE_ID=... pytest tests/test_live_workspace.py

Compiles every SQL statement the app sends (EXPLAIN, nothing is written) and sends one check-in to the
decision endpoint."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not (os.getenv("DATABRICKS_HOST") and os.getenv("NBO_WAREHOUSE_ID")),
    reason="set DATABRICKS_HOST, DATABRICKS_TOKEN and NBO_WAREHOUSE_ID to run live checks")

SCHEMA = os.getenv("NBO_LIVE_SCHEMA", "workspace.nbo_demo")
ENDPOINT = os.getenv("NBO_LIVE_ENDPOINT", "nbo-decision")


@pytest.fixture(scope="module")
def w():
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient()


@pytest.fixture()
def app_sql(monkeypatch):
    import importlib

    import pandas as pd
    monkeypatch.delenv("NBO_LOCAL_DATA", raising=False)
    monkeypatch.setenv("NBO_SCHEMA", SCHEMA)
    import data
    data = importlib.reload(data)
    data.st.cache_data.clear()
    seen = []
    monkeypatch.setattr(data, "_query", lambda s, p=None: seen.append((s, p or {})) or pd.DataFrame(
        {"member_id": [1], "event_ts": ["2026-09-30 07:00:00"], "n": [0]}))
    data.stores_by_traffic()
    data.store_feed(1001)
    data.event_bundle(42)
    data.table_counts(("instore_events",))
    data.log_decisions([{"event_id": 1, "store_id": 1001, "member_id": 7, "decision": "No offer",
                         "promotion_id": "", "channel": "", "latency_ms": 1.0}])
    for t in ["promotions", "featured_events", "tier_backtest", "promo_monthly", "promo_portfolio"]:
        data.table(t)
    return seen


def test_app_sql_compiles_against_live_tables(w, app_sql):
    from databricks.sdk.service.sql import StatementParameterListItem, StatementState
    errors = []
    for sql_text, params in app_sql:
        r = w.statement_execution.execute_statement(
            warehouse_id=os.environ["NBO_WAREHOUSE_ID"], statement=f"EXPLAIN {sql_text}", wait_timeout="50s",
            parameters=[StatementParameterListItem(name=k, value=None if v is None else str(v))
                        for k, v in params.items()])
        if r.status.state != StatementState.SUCCEEDED:
            errors.append(f"{r.status.error.message if r.status.error else r.status.state}\n{sql_text}")
            continue
        plan = " ".join(str(c) for row in (r.result.data_array or []) for c in row)
        if "error" in plan.lower() and "AnalysisException" in plan or "UNRESOLVED" in plan:
            errors.append(f"{plan[:400]}\n{sql_text}")
    assert not errors, "\n\n".join(errors)


def test_endpoint_returns_a_decision(w):
    from serving_model import RESPONSE_COLS
    rec = {"member_id": 0, "store_id": 0, "event_ts": "2026-09-30 07:00:00", "first_scan": "",
           "days_since_prev_visit": -1}
    ev = w.statement_execution.execute_statement(
        warehouse_id=os.environ["NBO_WAREHOUSE_ID"], wait_timeout="50s",
        statement=f"SELECT member_id, store_id FROM {SCHEMA}.instore_events LIMIT 1")
    rec["member_id"], rec["store_id"] = (int(x) for x in ev.result.data_array[0])
    out = w.serving_endpoints.query(name=ENDPOINT, dataframe_records=[rec])
    preds = out.predictions
    row = preds[0] if isinstance(preds, list) else preds
    assert set(RESPONSE_COLS) <= set(row)
