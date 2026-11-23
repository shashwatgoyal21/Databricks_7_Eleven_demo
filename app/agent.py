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
HURDLE = float(os.getenv("NBO_HURDLE_RATE", "0.101"))  # return each offer must clear, set by finance


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


# ---------------------------------------------------------------------------
# CFO view: return after discounts and compute vs the hurdle, report and EPM export
# ---------------------------------------------------------------------------

def cfo_table():
    """One row per promotion: return vs hurdle and cost per decision. Promotion level only."""
    p = data.table("offer_performance")
    if p.empty:
        return pd.DataFrame()
    names = data.table("promotions").set_index("promotion_id").short_name
    days = max(p.decision_date.nunique(), 1)
    g = p.groupby("promotion_id")[["offers_served", "holdout_checkins", "delivered", "accepted",
                                   "incremental_margin", "discount_cost", "compute_cost_usd", "net_return"]].sum()
    spend = g.discount_cost + g.compute_cost_usd
    out = pd.DataFrame({
        "Promotion": g.index.map(names),
        "Acceptance": g.accepted / g.delivered.where(g.delivered > 0),
        "Incremental margin / yr": g.incremental_margin * 365 / days,
        "Discounts / yr": g.discount_cost * 365 / days,
        "Compute / yr": g.compute_cost_usd * 365 / days,
        "Net return / yr": g.net_return * 365 / days,
        "Cost per decision": g.compute_cost_usd / (g.offers_served + g.holdout_checkins).clip(lower=1),
        "Return on spend": g.net_return / spend.where(spend > 0),
    })
    out["Clears hurdle"] = out["Return on spend"] >= HURDLE
    return out.sort_values("Net return / yr", ascending=False).reset_index(drop=True)


def cfo_report_html(b, t):
    """A one-page report for finance sign-off, in the Databricks brand system."""
    import html as h
    perf = b.get("perf") or {}
    above = int(t["Clears hurdle"].sum()) if not t.empty else 0
    rows = "".join(
        f"<tr><td>{h.escape(str(r.Promotion))}</td><td>{r.Acceptance:.0%}</td>"
        f"<td>{money(r['Net return / yr'], True)}</td><td>{r['Return on spend']:.0%}</td>"
        f"<td>${r['Cost per decision']:.5f}</td><td class='{'ok' if r['Clears hurdle'] else 'no'}'>"
        f"{'Yes' if r['Clears hurdle'] else 'No'}</td></tr>" for _, r in t.iterrows())
    recs = "".join(f"<li><b>{h.escape(r['title'])}.</b> {h.escape(r['why'])} Expected "
                   f"{money(r['impact'], True)} a month.</li>" for r in b["recs"])
    total = float(t["Net return / yr"].sum()) if not t.empty else 0.0
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Offer engine: finance report</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=DM+Mono&display=swap" rel="stylesheet">
<style>body{{font-family:'DM Sans',sans-serif;background:#F9F7F4;color:#0B2026;max-width:900px;margin:40px auto;padding:0 24px}}
h1{{font-size:28px;margin:0;border-bottom:3px solid #FF3621;padding-bottom:8px}}h2{{font-size:18px;margin-top:28px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:20px}}
.k{{background:#fff;border:1px solid #DBD7CE;border-radius:8px;padding:12px}}.k b{{display:block;font-size:22px}}
.k span{{font-size:12px;color:#4A5E68}}table{{width:100%;border-collapse:collapse;background:#fff;font-size:14px}}
th,td{{text-align:left;padding:8px;border-bottom:1px solid #EEEDE9}}th{{background:#1B3139;color:#fff;font-weight:500}}
.ok{{color:#00A972;font-weight:700}}.no{{color:#970F29;font-weight:700}}.note{{font-size:12px;color:#4A5E68}}
code{{font-family:'DM Mono',monospace}}</style></head><body>
<h1>In-store offer engine: finance report</h1>
<p class="note">Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC from Unity Catalog (<code>offer_performance</code>,
<code>compute_cost</code>, <code>agent_proposals</code>). Promotion-level results only.</p>
<div class="kpis">
<div class="k"><span>Net return a year, after discounts and compute</span><b>{money(total, True)}</b></div>
<div class="k"><span>Return on spend vs {HURDLE:.1%} hurdle</span><b>{perf.get("return_on_spend", 0):.0%}</b></div>
<div class="k"><span>Promotions clearing the hurdle</span><b>{above} of {len(t)}</b></div>
<div class="k"><span>Compute cost per decision</span><b>${perf.get("cost_per_decision", 0):.5f}</b></div></div>
<h2>Return by promotion</h2><table><tr><th>Promotion</th><th>Acceptance</th><th>Net return / yr</th>
<th>Return on spend</th><th>Cost per decision</th><th>Clears {HURDLE:.1%}</th></tr>{rows}</table>
<h2>Recommended changes, for approval</h2><ol>{recs}</ol>
<p class="note">Method: incremental margin = redemption rate when the offer is shown minus the rate in the 10% holdout,
times offers served, times unit margin. Net return = incremental margin - discounts - Databricks serving compute
(from system.billing). Return on spend = net return / (discounts + compute). Annualized from the measured period.</p>
</body></html>"""


def epm_export_csv():
    """Long-format actuals for Anaplan or Jedox: period, version, promotion, region, daypart, line item, value."""
    p = data.table("offer_performance")
    if p.empty:
        return ""
    items = {"offers_served": "Offers Served", "accepted": "Offers Accepted", "redeemed": "Offers Redeemed",
             "incremental_margin": "Incremental Margin", "discount_cost": "Discount Cost",
             "compute_cost_usd": "Compute Cost", "net_return": "Net Return"}
    long = p.melt(id_vars=["decision_date", "promotion_id", "region", "daypart"], value_vars=list(items),
                  var_name="line_item", value_name="value")
    long["line_item"] = long.line_item.map(items)
    long.insert(0, "version", "Actual")
    long["period"] = pd.to_datetime(long.pop("decision_date")).dt.strftime("%Y-%m-%d")
    long["value"] = long.value.astype(float).round(4)
    return long[["period", "version", "promotion_id", "region", "daypart", "line_item", "value"]].to_csv(index=False)
