"""Data access for the NBO app.

On Databricks: queries Unity Catalog tables through the SQL warehouse attached to the app
(DATABRICKS_WAREHOUSE_ID) and writes campaign approvals back to a Delta table.
Locally: set NBO_LOCAL_DATA to the folder written by local_run.py.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

SCHEMA = os.getenv("NBO_SCHEMA", "workspace.nbo_demo")
LOCAL_DIR = os.getenv("NBO_LOCAL_DATA")
LOCAL = bool(LOCAL_DIR)
APPROVALS_CSV = Path(LOCAL_DIR or ".") / "campaign_approvals.csv"


@st.cache_resource
def _connection():
    from databricks import sql
    from databricks.sdk.core import Config

    cfg = Config()
    return sql.connect(
        server_hostname=cfg.host,
        http_path=f"/sql/1.0/warehouses/{os.environ['DATABRICKS_WAREHOUSE_ID']}",
        credentials_provider=lambda: cfg.authenticate,
    )


def _query(sql_text, params=None):
    with _connection().cursor() as cur:
        cur.execute(sql_text, params or {})
        return cur.fetchall_arrow().to_pandas()


def source_label():
    if LOCAL:
        return f"Local preview from `{LOCAL_DIR}`"
    return f"Unity Catalog `{SCHEMA}` via Databricks SQL warehouse"


@st.cache_data(ttl=600)
def table(name):
    """Gold tables, read whole. Locally this includes member_offer_scores and member_profile."""
    if LOCAL:
        return pd.read_parquet(Path(LOCAL_DIR) / f"{name}.parquet")
    return _query(f"SELECT * FROM {SCHEMA}.{name}")


def _rows(name, eligible_only=False, **equals):
    """Rows of a table matching column = value filters, pushed down to the warehouse on Databricks."""
    if LOCAL:
        t = table(name)
        mask = t.eligible if eligible_only else pd.Series(True, index=t.index)
        for col, value in equals.items():
            mask &= t[col] == value
        return t[mask].reset_index(drop=True)
    where = " AND ".join([f"{col} = :{col}" for col in equals] + (["eligible"] if eligible_only else []))
    return _query(f"SELECT * FROM {SCHEMA}.{name} WHERE {where}", equals)


@st.cache_data(ttl=600)
def promotion_scores(promotion_id):
    return _rows("member_offer_scores", eligible_only=True, promotion_id=promotion_id)


@st.cache_data(ttl=600)
def member(member_id):
    """Profile row and all offer scores for one member, or (None, None)."""
    p = _rows("member_profile", member_id=member_id)
    if p.empty:
        return None, None
    return p.iloc[0], _rows("member_offer_scores", member_id=member_id)


def current_user():
    try:
        return st.context.headers.get("X-Forwarded-Email") or "demo.user@local"
    except Exception:
        return "demo.user@local"


@st.cache_data(ttl=60)
def approvals():
    if LOCAL:
        return pd.read_csv(APPROVALS_CSV) if APPROVALS_CSV.exists() else pd.DataFrame()
    try:
        return _query(f"SELECT * FROM {SCHEMA}.campaign_approvals ORDER BY approved_at DESC LIMIT 20")
    except Exception:
        return pd.DataFrame()


def approve(row):
    """Record an approved campaign. On Databricks this lands in a Delta table that a downstream
    activation job (Braze, the POS offer service, ...) would pick up."""
    row = {**row, "approved_by": current_user(),
           "approved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "status": "Approved"}
    approvals.clear()
    if LOCAL:
        pd.DataFrame([row]).to_csv(APPROVALS_CSV, mode="a", header=not APPROVALS_CSV.exists(), index=False)
        return
    _query(
        f"""INSERT INTO {SCHEMA}.campaign_approvals
            (promotion_id, promotion_name, strategy, audience_size, expected_redemptions,
             expected_discount_cost, expected_net_margin, channel, approved_by, approved_at, status)
            VALUES (:promotion_id, :promotion_name, :strategy, :audience_size, :expected_redemptions,
                    :expected_discount_cost, :expected_net_margin, :channel, :approved_by,
                    CAST(:approved_at AS TIMESTAMP), :status)""",
        row,
    )


# ---------------------------------------------------------------------------
# Genie
# ---------------------------------------------------------------------------

GENIE_SPACE_ID = os.getenv("GENIE_SPACE_ID", "").strip()


def genie_enabled():
    return bool(GENIE_SPACE_ID) and not LOCAL


@st.cache_resource
def _workspace():
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


def ask_genie(question):
    """Ask the Genie space one question. Returns {"texts": [...], "queries": [{description, sql, frame}]}."""
    w = _workspace()
    msg = w.genie.start_conversation_and_wait(GENIE_SPACE_ID, question)
    out = {"texts": [], "queries": []}
    for att in msg.attachments or []:
        if att.text and att.text.content:
            out["texts"].append(att.text.content)
        if att.query:
            res = {"description": att.query.description, "sql": att.query.query, "frame": None}
            try:
                qr = w.genie.get_message_attachment_query_result(
                    GENIE_SPACE_ID, msg.conversation_id, msg.message_id, att.attachment_id)
                stmt = qr.statement_response
                cols = [c.name for c in stmt.manifest.schema.columns]
                rows = (stmt.result.data_array or []) if stmt.result else []
                res["frame"] = pd.DataFrame(rows, columns=cols)
            except Exception:
                pass
            out["queries"].append(res)
    if not out["texts"] and not out["queries"]:
        out["texts"].append("Genie returned no answer. Try rephrasing the question.")
    return out
