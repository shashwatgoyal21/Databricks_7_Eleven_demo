"""The offer agent: the briefing on the Agent tab and the chat behind the floating button.

Briefing: what's working, what isn't, and recommended actions, computed from the gold tables
(promotion level and rates only, never individual shoppers).

Chat: a Multi-Agent Supervisor (Agent Bricks) that routes questions to the Genie space over the same
governed tables. The build job (src/07_agent.py) creates the supervisor, gives the app's service principal
permission to query it, and writes its endpoint name to the `agent_config` table, which the app reads here.
If no supervisor is set up yet, the chat asks the Genie space directly.
"""

import os
import uuid
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import data

AGENT_NAME = "NBO Offer Agent"


# ---------------------------------------------------------------------------
# Briefing
# ---------------------------------------------------------------------------

def money(x, signed=False):
    sign = "+" if signed and x > 0 else ("−" if x < 0 else "")
    return f"{sign}${abs(x):,.0f}"


@st.cache_data(ttl=600)
def decision_mix():
    """Share of today's check-ins by decision. Rates only."""
    d = data.table("offer_decisions")
    if d.empty:
        return None
    mix = d.decision.value_counts(normalize=True)
    served = d[d.decision == "Offer served"]
    by_promo = served.promotion_id.value_counts(normalize=True)
    return {
        "check_ins": len(d),
        "served": float(mix.get("Offer served", 0.0)),
        "no_offer": float(mix.get("No offer", 0.0)),
        "holdout": float(sum(v for k, v in mix.items() if str(k).startswith("Holdout"))),
        "by_promo": by_promo.to_dict(),
    }


@st.cache_data(ttl=600)
def performance():
    """Stored measures from offer_performance: acceptance, lift, net return and return on spend. Totals only."""
    p = data.table("offer_performance")
    if p.empty:
        return None
    s = p[["offers_served", "delivered", "accepted", "redeemed", "holdout_checkins", "holdout_redeemed",
           "incremental_margin", "discount_cost", "compute_cost_usd", "net_return"]].sum()
    spend = s.discount_cost + s.compute_cost_usd
    return {
        "acceptance_rate": s.accepted / s.delivered if s.delivered else 0.0,
        "redemption_rate": s.redeemed / s.offers_served if s.offers_served else 0.0,
        "holdout_rate": s.holdout_redeemed / s.holdout_checkins if s.holdout_checkins else 0.0,
        "net_return": float(s.net_return),
        "return_on_spend": float(s.net_return / spend) if spend else 0.0,
        "compute_cost": float(s.compute_cost_usd),
        "cost_per_decision": float(s.compute_cost_usd / max(s.offers_served + s.holdout_checkins, 1)),
        "days": int(p.decision_date.nunique()),
    }


def briefing():
    """Everything the Agent tab shows, as plain data."""
    pf = data.table("promo_portfolio").copy()
    bt = data.table("tier_backtest")
    promos = data.table("promotions").set_index("promotion_id")

    model_month = float(pf.targeted_net_margin_per_send.sum())
    rules_month = float(pf.blast_net_margin_per_send.sum())

    lift = {}
    for tier in ("Persuadable", "Sure Thing"):
        t = bt[(bt.tier == tier) & (bt.holdout_sends >= 30)]
        w = t.treatment_sends.sum()
        lift[tier] = float((t.measured_uplift * t.treatment_sends).sum() / w) if w else 0.0

    working, not_working, recs = [], [], []
    for r in pf.itertuples():
        name = r.short_name
        anyway = float(r.redemptions_that_would_happen_anyway)
        if r.targeted_net_margin_per_send <= 0:
            not_working.append({
                "title": f"{name} doesn't pay back for any shopper group",
                "detail": f"Measured lift is {r.measured_uplift_apr_sep * 100:+.1f} pts. At the current discount "
                          f"the best audience still nets {money(r.targeted_net_margin_per_send)} a month.",
            })
            recs.append({
                "promotion_id": r.promotion_id,
                "rank_value": abs(r.blast_net_margin_per_send),
                "kind": "Stop or switch",
                "title": f"Retire {name}, or switch it to a cheaper incentive",
                "why": f"No shopper group pays back at the current discount. Static rules lose "
                       f"{money(-r.blast_net_margin_per_send)} a month on it.",
                "impact": -r.blast_net_margin_per_send,
                "ask": f"What would happen to margin if we replaced {name} with a points offer instead of a discount?",
            })
        else:
            gain = r.targeted_net_margin_per_send - r.blast_net_margin_per_send
            working.append({
                "title": f"{name} earns {money(r.targeted_net_margin_per_send)} a month when the model targets it",
                "detail": f"Measured lift {r.measured_uplift_apr_sep * 100:+.1f} pts. "
                          f"{r.persuadable_members / max(r.eligible_members, 1):.0%} of eligible shoppers are "
                          f"persuadable.",
            })
            if r.blast_net_margin_per_send < 0:
                not_working.append({
                    "title": f"Sent to everyone, {name} loses {money(-r.blast_net_margin_per_send)} a month",
                    "detail": f"{anyway:.0%} of its redemptions would have happened without the offer.",
                })
            recs.append({
                "promotion_id": r.promotion_id,
                "rank_value": gain,
                "kind": "Scale" if r.blast_net_margin_per_send >= 0 else "Retarget",
                "title": (f"Scale {name} to more persuadable shoppers" if r.blast_net_margin_per_send >= 0
                          else f"Send {name} only to shoppers it changes"),
                "why": f"Targeted by the model it nets {money(r.targeted_net_margin_per_send)} a month, "
                       f"vs {money(r.blast_net_margin_per_send)} sent to everyone eligible.",
                "impact": gain,
                "ask": f"Which shopper segments and times of day drive the return on {name}?",
            })
    recs.sort(key=lambda x: -x["rank_value"])

    return {
        "model_month": model_month,
        "rules_month": rules_month,
        "lift": lift,
        "mix": decision_mix(),
        "perf": performance(),
        "working": working,
        "not_working": not_working,
        "recs": recs,
        "promo_names": promos.short_name.to_dict(),
    }


# ---------------------------------------------------------------------------
# Chat: supervisor endpoint, with Genie as the fallback
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def config():
    """Agent settings: app.yaml env vars first, then the agent_config table written by the build job."""
    cfg = {"endpoint": os.getenv("AGENT_ENDPOINT", "").strip(), "genie_space_id": data.GENIE_SPACE_ID}
    if data.LOCAL:
        return cfg
    try:
        rows = data._query(f"SELECT key, value FROM {data.SCHEMA}.agent_config")
        kv = dict(zip(rows.key, rows.value))
        cfg["endpoint"] = cfg["endpoint"] or kv.get("supervisor_endpoint", "")
        cfg["genie_space_id"] = cfg["genie_space_id"] or kv.get("genie_space_id", "")
    except Exception:
        pass
    return cfg


def mode():
    cfg = config()
    if data.LOCAL:
        return "local"
    if cfg["endpoint"]:
        return "supervisor"
    if cfg["genie_space_id"]:
        return "genie"
    return "none"


def _supervisor(history):
    """Ask the supervisor. history = [{"role", "content"}]. Returns (text, routed_to)."""
    w = data._workspace()
    resp = w.api_client.do("POST", f"/serving-endpoints/{config()['endpoint']}/invocations",
                           body={"input": history})
    texts, tools = [], []
    for item in resp.get("output", []) or []:
        if item.get("type") == "message":
            for c in item.get("content", []) or []:
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    texts.append(c["text"])
        elif item.get("type") == "function_call":
            tools.append(item.get("name", "tool"))
    if not texts and resp.get("choices"):  # chat-completions shaped endpoint
        texts.append(resp["choices"][0]["message"]["content"])
    routed = "Genie space" if any("genie" in t.lower() or "nbo_performance" in t.lower() for t in tools) else (
        ", ".join(dict.fromkeys(tools)) if tools else "")
    return ("\n\n".join(texts) or "The agent returned no answer. Try rephrasing the question."), routed


def _genie(question):
    space = config()["genie_space_id"]
    old, data.GENIE_SPACE_ID = data.GENIE_SPACE_ID, space
    try:
        out = data.ask_genie(question)
    finally:
        data.GENIE_SPACE_ID = old
    parts = list(out["texts"])
    tables = [q["frame"] for q in out["queries"] if q.get("frame") is not None]
    sqls = [q["sql"] for q in out["queries"] if q.get("sql")]
    return "\n\n".join(parts), "Genie space", tables, sqls


def _local_answer(question):
    """Local preview: answer from the briefing so the chat can be tried without a workspace."""
    b = briefing()
    q = question.lower()
    if any(k in q for k in ("not working", "lose", "losing", "worst", "stop", "retire")):
        lines = [f"- **{n['title']}.** {n['detail']}" for n in b["not_working"]]
        return "Here's what isn't working:\n\n" + "\n".join(lines)
    if any(k in q for k in ("recommend", "should", "next", "do")):
        lines = [f"{i}. **{r['title']}.** {r['why']}" for i, r in enumerate(b["recs"][:3], 1)]
        return "My top recommendations, ranked by monthly margin:\n\n" + "\n".join(lines)
    lines = [f"- **{w['title']}.** {w['detail']}" for w in b["working"]]
    return ("Local preview: the chat answers from the briefing. On Databricks it goes to the supervisor and "
            "the Genie space.\n\nWhat's working:\n\n" + "\n".join(lines))


def ask(history):
    """history ends with the user's question. Returns a message dict for the chat log."""
    question = history[-1]["content"]
    m = mode()
    try:
        if m == "supervisor":
            text, routed = _supervisor(history)
            return {"role": "assistant", "content": text, "routed": routed or "Offer agent"}
        if m == "genie":
            text, routed, tables, sqls = _genie(question)
            return {"role": "assistant", "content": text or "Genie returned no answer.", "routed": routed,
                    "tables": tables, "sql": sqls}
        if m == "local":
            return {"role": "assistant", "content": _local_answer(question), "routed": "Local preview"}
        return {"role": "assistant", "routed": "Setup needed",
                "content": "The agent isn't connected yet. Run the build job's `agent` task (it creates the "
                           "supervisor and the Genie space), or set `GENIE_SPACE_ID` in app.yaml."}
    except Exception as e:  # show the reason, never a stack trace
        return {"role": "assistant", "routed": "Error",
                "content": f"The agent couldn't answer: {str(e).splitlines()[0][:200]}"}


# ---------------------------------------------------------------------------
# Ledger: every proposal and every question is stored in Unity Catalog
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def record_proposals(recs):
    """Store today's recommendations in agent_proposals, once per app session, with status 'proposed'."""
    if st.session_state.get("_proposals_logged"):
        return
    st.session_state["_proposals_logged"] = True
    today, now = datetime.now(timezone.utc).strftime("%Y-%m-%d"), _now()
    seen = set()
    if not data.LOCAL:
        try:
            seen = set(data._query(f"SELECT proposal_id FROM {data.SCHEMA}.agent_proposals "
                                   f"WHERE proposal_date = current_date()").proposal_id)
        except Exception:
            pass
    recs = [r for r in recs if f"{today}-{r['promotion_id']}-{r['kind']}" not in seen]
    data.append_rows("agent_proposals", [{
        "proposal_id": f"{today}-{r['promotion_id']}-{r['kind']}", "proposal_date": today,
        "promotion_id": r["promotion_id"], "kind": r["kind"], "title": r["title"], "rationale": r["why"],
        "expected_monthly_impact_usd": float(r["impact"]), "status": "proposed", "decided_by": None,
        "decided_at": None, "created_at": now} for r in recs])


def record_activity(kind, content, routed=""):
    """Store a question asked of the agent (or an action it took) in agent_activity."""
    data.append_rows("agent_activity", [{
        "activity_id": str(uuid.uuid4()), "activity_type": kind, "content": content[:2000], "routed_to": routed,
        "user_name": data.current_user(), "created_at": _now()}])
