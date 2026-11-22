"""Data access for the real-time NBO app.

On Databricks: queries Unity Catalog tables through the SQL warehouse attached to the app
(DATABRICKS_WAREHOUSE_ID) and appends every decision the app makes to `live_decision_log`.
Locally: set NBO_LOCAL_DATA to the folder written by local_run.py.

Production path (talk track): member features and uplift scores are served from a Lakebase synced
table / online feature store, and the decision runs behind a Model Serving endpoint. The app reads
the same Unity Catalog tables through the warehouse, prefetching one store's shoppers at a time.
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

SCHEMA = os.getenv("NBO_SCHEMA", "workspace.nbo_demo")
LOCAL_DIR = os.getenv("NBO_LOCAL_DATA")
LOCAL = bool(LOCAL_DIR)
LOG_CSV = Path(LOCAL_DIR or ".") / "live_decision_log.csv"
ENDPOINT = os.getenv("NBO_ENDPOINT", "")


PROFILE_COLS = ["member_id", "first_name", "last_name", "crm_segment", "region", "home_store_id", "tenure_months",
                "app_user", "marketing_opt_in", "visits", "visits_per_active_week", "avg_basket_value",
                "coffee_rate", "pastry_with_coffee_rate", "morning_share", "midday_share", "afternoon_share",
                "late_night_share", "roller_grill_rate", "sandwich_rate", "energy_drink_rate"]


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


def _local(name):
    return pd.read_parquet(Path(LOCAL_DIR) / f"{name}.parquet")


def source_label():
    if LOCAL:
        return f"Local preview from `{LOCAL_DIR}`"
    return f"Unity Catalog `{SCHEMA}` via Databricks SQL warehouse"


@st.cache_data(ttl=600)
def table(name):
    """Small gold tables, read whole."""
    if LOCAL:
        return _local(name)
    return _query(f"SELECT * FROM {SCHEMA}.{name}")


@st.cache_data(ttl=600)
def stores_by_traffic():
    """Stores with check-in counts on the live day, busiest first."""
    if LOCAL:
        ev = _local("instore_events")
        st_ = _local("stores")
        c = ev.groupby("store_id").size().rename("check_ins").reset_index()
        return c.merge(st_, on="store_id").sort_values("check_ins", ascending=False).reset_index(drop=True)
    return _query(f"""SELECT e.store_id, COUNT(*) AS check_ins, s.region, s.city, s.has_fresh_bakery
                      FROM {SCHEMA}.instore_events e JOIN {SCHEMA}.stores s USING (store_id)
                      GROUP BY e.store_id, s.region, s.city, s.has_fresh_bakery
                      ORDER BY check_ins DESC""")


@st.cache_data(ttl=600)
def store_feed(store_id):
    """Everything the decision path needs for one store's live day, fetched once:
    the check-in stream, the shoppers' uplift scores (all promotions), and their profiles.
    Returns (events, scores, profiles, fetch_ms)."""
    t0 = time.perf_counter()
    if LOCAL:
        ev = _local("instore_events")
        ev = ev[ev.store_id == store_id].sort_values("event_ts").reset_index(drop=True)
        ids = set(ev.member_id)
        sc = _local("member_offer_scores")
        sc = sc[sc.member_id.isin(ids)].reset_index(drop=True)
        pr = _local("member_profile")
        pr = pr[pr.member_id.isin(ids)][PROFILE_COLS].reset_index(drop=True)
    else:
        p = {"store_id": int(store_id)}
        sub = f"SELECT DISTINCT member_id FROM {SCHEMA}.instore_events WHERE store_id = :store_id"
        ev = _query(f"SELECT * FROM {SCHEMA}.instore_events WHERE store_id = :store_id ORDER BY event_ts", p)
        sc = _query(f"""SELECT member_id, promotion_id, eligible, p_without_offer, p_with_offer, uplift,
                               expected_net_margin, tier, reason
                        FROM {SCHEMA}.member_offer_scores WHERE member_id IN ({sub})""", p)
        pr = _query(f"SELECT {', '.join(PROFILE_COLS)} FROM {SCHEMA}.member_profile WHERE member_id IN ({sub})", p)
    ev["event_ts"] = pd.to_datetime(ev.event_ts)
    return ev, sc, pr, (time.perf_counter() - t0) * 1000


@st.cache_data(ttl=600)
def event_bundle(event_id):
    """One check-in with its shopper's scores and profile, for the decision trace."""
    if LOCAL:
        ev = _local("instore_events")
        ev = ev[ev.event_id == event_id].reset_index(drop=True)
        if ev.empty:
            return None, None, None
        mid = int(ev.member_id.iloc[0])
        sc = _local("member_offer_scores")
        pr = _local("member_profile")
        return ev, sc[sc.member_id == mid].reset_index(drop=True), pr[pr.member_id == mid][PROFILE_COLS]
    p = {"event_id": int(event_id)}
    ev = _query(f"SELECT * FROM {SCHEMA}.instore_events WHERE event_id = :event_id", p)
    if ev.empty:
        return None, None, None
    m = {"member_id": int(ev.member_id.iloc[0])}
    sc = _query(f"SELECT * FROM {SCHEMA}.member_offer_scores WHERE member_id = :member_id", m)
    pr = _query(f"SELECT {', '.join(PROFILE_COLS)} FROM {SCHEMA}.member_profile WHERE member_id = :member_id", m)
    ev["event_ts"] = pd.to_datetime(ev.event_ts)
    return ev, sc, pr


@st.cache_data(ttl=600)
def table_counts(names):
    """Row counts for the pipeline view."""
    if LOCAL:
        return {n: len(_local(n)) if (Path(LOCAL_DIR) / f"{n}.parquet").exists() else None for n in names}
    out = {}
    for n in names:
        try:
            out[n] = int(_query(f"SELECT COUNT(*) AS n FROM {SCHEMA}.{n}").n.iloc[0])
        except Exception:
            out[n] = None
    return out


@st.cache_resource
def _local_service():
    """Local stand-in for the endpoint: same learners and code, features read from parquet."""
    import pickle

    import nbo_decision as nd

    with open(Path(LOCAL_DIR) / "uplift_learners.pkl", "rb") as fh:
        models = pickle.load(fh)
    feats = _local("member_features").set_index("member_id")[
        nd.MODEL_FEATURES + ["marketing_opt_in", "days_since_last_visit"]]
    return models, feats


@st.cache_resource
def _local_stores():
    return _local("stores").set_index("store_id")[["has_fresh_bakery", "region", "city"]]


@st.cache_resource
def _workspace():
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


GENIE_SPACE_ID = os.getenv("GENIE_SPACE_ID", "").strip()


def genie_enabled():
    return bool(GENIE_SPACE_ID) and not LOCAL


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


def endpoint_label():
    if LOCAL:
        return "in-process copy of the decision service (local preview)"
    return f"Model Serving endpoint `{ENDPOINT}`" if ENDPOINT else "in-app fallback"


def call_decision_service(event):
    """Send one check-in to the real-time decision service. Returns (request, response dict, round-trip ms)
    or (request, None, ms) if the service is unavailable."""
    import nbo_decision as nd

    req = {c: event[c] for c in nd.CHECKIN_FIELDS}
    req = {k: (v.item() if hasattr(v, "item") else v) for k, v in req.items()}
    req["event_ts"] = pd.Timestamp(req["event_ts"]).strftime("%Y-%m-%d %H:%M:%S")
    t0 = time.perf_counter()
    try:
        if LOCAL:
            models, feats = _local_service()
            if req["member_id"] not in feats.index:
                return req, None, 0.0
            store = _local_stores().loc[[req["store_id"]]].reset_index(drop=True)
            row = pd.concat([pd.DataFrame([req]), feats.loc[[req["member_id"]]].reset_index(drop=True), store],
                            axis=1)
            resp = nd.score_and_decide(row, models).iloc[0].to_dict()
        elif ENDPOINT:
            out = _workspace().serving_endpoints.query(name=ENDPOINT, dataframe_records=[req])
            preds = out.predictions
            resp = preds[0] if isinstance(preds, list) else pd.DataFrame(preds).iloc[0].to_dict()
        else:
            return req, None, 0.0
    except Exception as e:
        st.session_state["endpoint_error"] = str(e).splitlines()[0][:200]
        return req, None, (time.perf_counter() - t0) * 1000
    return req, resp, (time.perf_counter() - t0) * 1000


def current_user():
    try:
        return st.context.headers.get("X-Forwarded-Email") or "demo.user@local"
    except Exception:
        return "demo.user@local"


def log_decisions(rows):
    """Append decisions made in this app session to live_decision_log (Unity Catalog on Databricks)."""
    if not rows:
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    df = pd.DataFrame(rows).assign(logged_by=current_user(), logged_at=now)
    if LOCAL:
        df.to_csv(LOG_CSV, mode="a", header=not LOG_CSV.exists(), index=False)
        return
    try:
        values, params = [], {}
        for i, r in enumerate(df.to_dict("records")):
            keys = ["event_id", "store_id", "member_id", "decision", "promotion_id", "channel", "latency_ms",
                    "logged_by", "logged_at"]
            values.append("(" + ", ".join(f":{k}{i}" if k != "logged_at" else f"CAST(:{k}{i} AS TIMESTAMP)"
                                          for k in keys) + ")")
            for k in keys:
                v = r.get(k)
                params[f"{k}{i}"] = None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)
        _query(f"""INSERT INTO {SCHEMA}.live_decision_log
                   (event_id, store_id, member_id, decision, promotion_id, channel, latency_ms, logged_by, logged_at)
                   VALUES {", ".join(values)}""", params)
    except Exception as e:  # logging must never break the live demo
        st.toast(f"Decision log write skipped: {str(e).splitlines()[0][:120]}")
