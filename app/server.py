"""In-store offer engine: the API behind the React front end, and the front end itself (static/).

Every number comes from the Unity Catalog tables the build job writes (or .local_data/ in local preview), scaled
to the network with the `finance_assumptions` table. Recommendations come from the trained recommender
(`agent_proposals`). Run locally:

    cd app && NBO_LOCAL_DATA=../.local_data uvicorn server:app --port 8000
"""

import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agent
import data
import finance

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="In-Store Offer Engine")
STATIC = Path(__file__).parent / "static"


@app.middleware("http")
async def who(request: Request, call_next):
    token = data.USER.set(request.headers.get("X-Forwarded-Email") or "demo.user@local")
    try:
        return await call_next(request)
    finally:
        data.USER.reset(token)


@app.exception_handler(Exception)
async def errors(request: Request, exc: Exception):
    logging.exception("API error")
    return JSONResponse({"error": str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__},
                        status_code=500)


def clean(x):
    """JSON-safe: numpy scalars to Python, NaN to None."""
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if np.isnan(x) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m-%d")
    return x


def _names():
    return data.table("promotions").set_index("promotion_id").short_name.to_dict()


def _status(row, hurdle):
    if not row["enough_data"]:
        return "Collecting data"
    r = row["roic"]
    if r is None or np.isnan(r):
        return "Collecting data"
    if r >= 2 * hurdle:
        return "Scale up"
    if r >= hurdle:
        return "Performing"
    if r >= 0:
        return "Watch"
    return "Losing money"


def _programs():
    """One row per promotion: live-day results scaled to the network, plus promotions not run by the engine."""
    t, total = finance.network_pnl()
    perf = data.table("offer_performance")
    names = _names()
    hurdle = finance.assumptions()["hurdle_rate"]
    lift = {}
    if not perf.empty:
        g = perf.groupby("promotion_id")[["redeemed", "offers_served", "holdout_redeemed", "holdout_checkins"]].sum()
        lift = (g.redeemed / g.offers_served.where(g.offers_served > 0)
                - g.holdout_redeemed / g.holdout_checkins.where(g.holdout_checkins > 0)).to_dict()
    rows = []
    running = set(t.promotion_id) if not t.empty else set()
    for r in (t.to_dict("records") if not t.empty else []):
        rows.append({"id": r["promotion_id"], "name": names.get(r["promotion_id"], r["promotion_id"]),
                     "status": _status(r, hurdle), "offers": r["offers_served"],
                     "min_offers": finance.MIN_OFFERS, "acceptance": r["acceptance_rate"],
                     "lift": lift.get(r["promotion_id"]), "sales": r["incremental_sales"],
                     "profit": r["operating_profit"], "roic": r["roic"] if r["enough_data"] else None})
    for pid, name in names.items():
        if pid not in running:
            rows.append({"id": pid, "name": name, "status": "Not running", "offers": 0,
                         "min_offers": finance.MIN_OFFERS, "acceptance": None, "lift": None, "sales": None,
                         "profit": None, "roic": None})
    order = {"Scale up": 0, "Performing": 1, "Watch": 2, "Losing money": 3, "Collecting data": 4, "Not running": 5}
    return sorted(rows, key=lambda x: (order[x["status"]], -(x["roic"] or 0))), total


@app.get("/api/overview")
def overview():
    programs, total = _programs()
    n_stores, days = finance.pilot_scope()
    perf = data.table("offer_performance")
    hist = data.table("promo_monthly")
    trend = []
    if not hist.empty:
        m = hist.assign(net=hist.incremental_margin - hist.discount_cost).groupby("month_end")[["net", "sends"]].sum()
        trend = [{"label": pd.Timestamp(k).strftime("%b"), "value": float(v.net / v.sends), "engine": False}
                 for k, v in m.iterrows() if v.sends]
    if not perf.empty and perf.offers_served.sum():
        net = (perf.incremental_margin - perf.discount_cost).sum() / perf.offers_served.sum()
        trend.append({"label": "Engine", "value": float(net), "engine": True})
    dates = pd.to_datetime(perf.decision_date) if not perf.empty else pd.Series(dtype="datetime64[ns]")
    p = agent.pending()
    return clean({
        "scope": {"pilot_stores": n_stores, "days": days, "network_stores": total.get("network_stores"),
                  "start": dates.min().strftime("%b %-d, %Y") if len(dates) else None,
                  "end": dates.max().strftime("%b %-d, %Y") if len(dates) else None},
        "kpis": {"sales": total.get("incremental_sales"), "profit": total.get("operating_profit"),
                 "roic": total.get("roic"), "hurdle": total.get("hurdle_rate"),
                 "cost_per_1k": (total.get("cost_per_decision") or 0) * 1000,
                 "acceptance": total.get("acceptance_rate")},
        "programs": [{"id": r["id"], "name": r["name"], "roic": r["roic"], "status": r["status"]} for r in programs],
        "trend": trend,
        "recommendations": p[:3], "pending_count": len(p),
        "model": {"name": p[0]["model_name"], "version": p[0]["model_version"], "scored_at": p[0]["scored_at"]}
        if p else None,
    })


@app.get("/api/recommendations")
def recommendations():
    cur = agent.all_current()
    meta = next(({"name": r["model_name"], "version": r["model_version"], "scored_at": r["scored_at"]}
                 for r in cur), None)
    return clean({"items": cur, "decided": agent.decided(), "model": meta,
                  "pending_count": sum(r["status"] == "proposed" for r in cur)})


class Decision(BaseModel):
    status: str
    reason: str | None = None


@app.post("/api/recommendations/{proposal_id}/decision")
def decision(proposal_id: str, d: Decision):
    try:
        return clean(agent.decide(proposal_id, d.status, d.reason))
    except KeyError:
        raise HTTPException(404, "Recommendation not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/programs")
def programs():
    rows, _ = _programs()
    return clean({"items": rows, "hurdle": finance.assumptions()["hurdle_rate"]})


@app.get("/api/programs/{pid}")
def program(pid: str):
    rows, _ = _programs()
    row = next((r for r in rows if r["id"] == pid), None)
    if row is None:
        raise HTTPException(404, "Program not found")
    perf = data.table("offer_performance")
    perf = perf[perf.promotion_id == pid]
    cells = []
    if not perf.empty:
        g = perf.groupby(["region", "daypart"])[["offers_served", "accepted", "delivered", "net_return",
                                                 "discount_cost", "compute_cost_usd"]].sum().reset_index()
        g["acceptance"] = g.accepted / g.delivered.where(g.delivered > 0)
        g["return_on_spend"] = g.net_return / (g.discount_cost + g.compute_cost_usd).where(lambda s: s > 0)
        cells = g[["region", "daypart", "offers_served", "acceptance", "return_on_spend"]].to_dict("records")
    hist = data.table("promo_monthly")
    hist = hist[hist.promotion_id == pid]
    trend = []
    if not hist.empty:
        m = hist.assign(net=hist.incremental_margin - hist.discount_cost).groupby("month_end")[["net", "sends"]].sum()
        trend = [{"label": pd.Timestamp(k).strftime("%b"), "value": float(v.net / v.sends), "engine": False}
                 for k, v in m.iterrows() if v.sends]
    if not perf.empty and perf.offers_served.sum():
        trend.append({"label": "Engine", "engine": True,
                      "value": float((perf.incremental_margin - perf.discount_cost).sum() / perf.offers_served.sum())})
    recs = [r for r in agent.all_current() if r["promotion_id"] == pid]
    return clean({**row, "cells": cells, "trend": trend, "recommendations": recs})


@app.get("/api/system")
def system():
    out = {"steps": [], "model": {}, "recommender": {}, "cost": {}, "governance": {}}
    ev = data.table("offer_decisions")
    if not ev.empty:
        mix = ev.decision.value_counts(normalize=True)
        out["steps"] = [
            {"label": "Check-ins", "value": len(ev), "fmt": "int"},
            {"label": "Offers served", "value": float(mix.get("Offer served", 0)), "fmt": "pct"},
            {"label": "Control group", "value": float(sum(v for k, v in mix.items() if str(k).startswith("Holdout"))),
             "fmt": "pct"},
            {"label": "No offer", "value": float(mix.get("No offer", 0)), "fmt": "pct"},
        ]
    lat = None
    try:
        log = data.table("live_decision_log")
        if not log.empty and "latency_ms" in log:
            lat = float(pd.to_numeric(log.latency_ms, errors="coerce").dropna().quantile(0.95))
    except Exception:
        pass
    out["steps"].append({"label": "Latency p95", "value": lat, "fmt": "ms"})
    _, total = finance.network_pnl()
    try:
        cc = data.table("compute_cost").sort_values("measured_at").iloc[-1]
        src = str(cc.source)
    except Exception:
        src = "estimate"
    out["cost"] = {"per_1k": (total.get("cost_per_decision") or 0) * 1000, "network_year": total.get("compute_cost"),
                   "platform_year": total.get("platform_cost"), "source": src}
    out["model"] = {"endpoint": data.ENDPOINT or None, "uplift_model": f"{data.SCHEMA}.nbo_uplift_model",
                    "version": _model_version(f"{data.SCHEMA}.nbo_uplift_model")}
    cur = agent.all_current()
    out["recommender"] = {"name": f"{data.SCHEMA}.nbo_recommender",
                          "version": cur[0]["model_version"] if cur else None,
                          "scored_at": cur[0]["scored_at"] if cur else None, "proposals": len(cur)}
    out["governance"] = {"row_filter": "nbo_region_filter", "masked": "first_name, last_name, email",
                         "app_scope": "Promotion, region, daypart", "approvals": "promotion_changes"}
    return clean(out)


def _model_version(name):
    if data.LOCAL:
        return "local"
    try:
        versions = list(data._workspace().model_versions.list(name))
        return str(max(int(v.version) for v in versions)) if versions else None
    except Exception:
        return None


@app.get("/api/reports")
def reports():
    open_url, embed = agent.dashboard_urls()
    return {"open_url": open_url, "embed_url": embed}


@app.get("/api/reports/finance.html")
def finance_report():
    t, total = agent.finance_table()
    return HTMLResponse(agent.finance_report_html(t, total))


@app.get("/api/reports/epm.csv")
def epm():
    return Response(agent.epm_export_csv(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=offer_engine_epm.csv"})


class Ask(BaseModel):
    history: list[dict]


@app.post("/api/ask")
def ask(q: Ask):
    msg = agent.ask(q.history)
    agent.record_activity("question", q.history[-1].get("content", ""), msg.get("routed", ""))
    tables = [f.head(50).astype(object).where(f.notna(), None).to_dict("split") for f in msg.pop("tables", []) or []]
    return clean({**msg, "tables": tables, "sql": msg.get("sql", [])})


@app.get("/api/health")
def health():
    return {"ok": True, "source": data.source_label()}


if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/{path:path}")
def spa(path: str):
    index = STATIC / "index.html"
    if not index.exists():
        return HTMLResponse("Front end not built. Run: cd frontend && npm install && npm run build", 503)
    return FileResponse(index)
