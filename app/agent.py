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
import finance

AGENT_NAME = "NBO Offer Agent"
HURDLE = float(os.getenv("NBO_HURDLE_RATE", "0.101"))  # return each offer must clear, set by finance


# ---------------------------------------------------------------------------
# Briefing
# ---------------------------------------------------------------------------

def money(x, signed=False):
    """$12.4M, $310K, $950: the scale finance reads at."""
    sign = "+" if signed and x > 0 else ("−" if x < 0 else "")
    a = abs(x)
    body = f"{a / 1e9:.2f}B" if a >= 1e9 else f"{a / 1e6:.1f}M" if a >= 1e6 else f"{a / 1e3:.0f}K" if a >= 1e3 else f"{a:,.0f}"
    return f"{sign}${body}"


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
    # promo_portfolio is per month for the pilot stores: scale to the network, per year
    n_stores, _ = finance.pilot_scope()
    k = finance.assumptions()["network_stores"] / n_stores * 12
    for c in ("targeted_net_margin_per_send", "blast_net_margin_per_send"):
        pf[c] = pf[c] * k
    bt = data.table("tier_backtest")
    promos = data.table("promotions").set_index("promotion_id")

    model_year = float(pf.targeted_net_margin_per_send.sum())
    rules_year = float(pf.blast_net_margin_per_send.sum())

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
                          f"the best audience still nets {money(r.targeted_net_margin_per_send)} a year.",
            })
            recs.append({
                "promotion_id": r.promotion_id,
                "rank_value": abs(r.blast_net_margin_per_send),
                "kind": "Stop or switch",
                "title": f"Retire {name}, or switch it to a cheaper incentive",
                "why": f"No shopper group pays back at the current discount. Static rules lose "
                       f"{money(-r.blast_net_margin_per_send)} a year on it.",
                "impact": -r.blast_net_margin_per_send,
                "ask": f"What would happen to margin if we replaced {name} with a points offer instead of a discount?",
            })
        else:
            gain = r.targeted_net_margin_per_send - r.blast_net_margin_per_send
            working.append({
                "title": f"{name} earns {money(r.targeted_net_margin_per_send)} a year when the model targets it",
                "detail": f"Measured lift {r.measured_uplift_apr_sep * 100:+.1f} pts. "
                          f"{r.persuadable_members / max(r.eligible_members, 1):.0%} of eligible shoppers are "
                          f"persuadable.",
            })
            if r.blast_net_margin_per_send < 0:
                not_working.append({
                    "title": f"Sent to everyone, {name} loses {money(-r.blast_net_margin_per_send)} a year",
                    "detail": f"{anyway:.0%} of its redemptions would have happened without the offer.",
                })
            recs.append({
                "promotion_id": r.promotion_id,
                "rank_value": gain,
                "kind": "Scale" if r.blast_net_margin_per_send >= 0 else "Retarget",
                "title": (f"Scale {name} to more persuadable shoppers" if r.blast_net_margin_per_send >= 0
                          else f"Send {name} only to shoppers it changes"),
                "why": f"Targeted by the model it nets {money(r.targeted_net_margin_per_send)} a year, "
                       f"vs {money(r.blast_net_margin_per_send)} sent to everyone eligible.",
                "impact": gain,
                "ask": f"Which shopper segments and times of day drive the return on {name}?",
            })
    recs.sort(key=lambda x: -x["rank_value"])

    return {
        "model_year": model_year,
        "rules_year": rules_year,
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
        return "My top recommendations, ranked by yearly margin:\n\n" + "\n".join(lines)
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
        "expected_monthly_impact_usd": float(r["impact"]) / 12, "status": "proposed", "decided_by": None,
        "decided_at": None, "created_at": now} for r in recs])


def record_activity(kind, content, routed=""):
    """Store a question asked of the agent (or an action it took) in agent_activity."""
    data.append_rows("agent_activity", [{
        "activity_id": str(uuid.uuid4()), "activity_type": kind, "content": content[:2000], "routed_to": routed,
        "user_name": data.current_user(), "created_at": _now()}])



# ---------------------------------------------------------------------------
# Finance view: top line, bottom line and ROIC vs the hurdle; report and EPM export
# ---------------------------------------------------------------------------

def finance_table():
    t, total = finance.network_pnl()
    if t.empty:
        return t, total
    names = data.table("promotions").set_index("promotion_id").short_name
    out = pd.DataFrame({
        "Promotion": t.promotion_id.map(names),
        "Acceptance": t.acceptance_rate,
        "Incremental sales ($M/yr)": t.incremental_sales / 1e6,
        "Gross profit after discount ($M/yr)": t.gross_profit_after_discount / 1e6,
        "Compute + platform ($M/yr)": (t.compute_cost + t.platform_cost) / 1e6,
        "Operating profit ($M/yr)": t.operating_profit / 1e6,
        "ROIC": t.roic,
        "Clears hurdle": t.clears_hurdle,
    })
    return out.sort_values("ROIC", ascending=False).reset_index(drop=True), total


def finance_report_html(b, t, total):
    """One-page report for CFO sign-off, in the Databricks brand system."""
    import html as h
    a = finance.assumptions()
    rows = "".join(
        f"<tr><td>{h.escape(str(r.Promotion))}</td><td>{money(r['Incremental sales ($M/yr)'] * 1e6)}</td>"
        f"<td>{money(r['Operating profit ($M/yr)'] * 1e6, True)}</td><td>{r.ROIC:.1%}</td>"
        f"<td class='{'ok' if r['Clears hurdle'] else 'no'}'>{'Yes' if r['Clears hurdle'] else 'No'}</td></tr>"
        for _, r in t.iterrows())
    recs = "".join(f"<li><b>{h.escape(r['title'])}.</b> {h.escape(r['why'])}</li>" for r in b["recs"])
    assump = "".join(f"<tr><td>{h.escape(k)}</td><td>{a[k]:,.3g}</td><td>{h.escape(v[2])}</td></tr>"
                     for k, v in finance.DEFAULTS.items())
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Offer engine: finance report</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=DM+Mono&display=swap" rel="stylesheet">
<style>body{{font-family:'DM Sans',sans-serif;background:#F9F7F4;color:#0B2026;max-width:920px;margin:40px auto;padding:0 24px}}
h1{{font-size:28px;margin:0;border-bottom:3px solid #FF3621;padding-bottom:8px}}h2{{font-size:18px;margin-top:28px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:20px}}
.k{{background:#fff;border:1px solid #DBD7CE;border-radius:8px;padding:12px}}.k b{{display:block;font-size:22px}}
.k span{{font-size:12px;color:#4A5E68}}table{{width:100%;border-collapse:collapse;background:#fff;font-size:14px}}
th,td{{text-align:left;padding:8px;border-bottom:1px solid #EEEDE9;vertical-align:top}}th{{background:#1B3139;color:#fff;font-weight:500}}
.ok{{color:#00A972;font-weight:700}}.no{{color:#970F29;font-weight:700}}.note{{font-size:12px;color:#4A5E68}}
code{{font-family:'DM Mono',monospace}}</style></head><body>
<h1>In-store offer engine: finance report</h1>
<p class="note">Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC from Unity Catalog. Measured in the pilot stores,
scaled to {total['network_stores']:,.0f} stores, per year. Promotion-level results only.</p>
<div class="kpis">
<div class="k"><span>Top line: incremental sales a year</span><b>{money(total['incremental_sales'])}</b></div>
<div class="k"><span>Bottom line: operating profit impact a year</span><b>{money(total['operating_profit'], True)}</b></div>
<div class="k"><span>ROIC vs {total['hurdle_rate']:.1%} hurdle</span><b>{total['roic']:.1%}</b></div>
<div class="k"><span>Databricks compute per decision</span><b>${total['cost_per_decision']:.5f}</b></div></div>
<h2>By promotion</h2><table><tr><th>Promotion</th><th>Incremental sales / yr</th><th>Operating profit / yr</th>
<th>ROIC</th><th>Clears hurdle</th></tr>{rows}</table>
<h2>Recommended changes, for approval</h2><ol>{recs}</ol>
<h2>Assumptions (finance_assumptions table)</h2><table><tr><th>Key</th><th>Value</th><th>Meaning</th></tr>{assump}</table>
<p class="note">Incremental margin = (redemption rate when shown - rate in the 10% holdout) x offers served x unit margin,
less cannibalization. Incremental sales = incremental margin / gross margin rate. Operating profit impact = incremental
margin - discounts - Databricks compute (system.billing) - platform cost. ROIC = operating profit impact / capital deployed
(discounts + compute + platform cost).</p></body></html>"""


def epm_export_csv():
    """Long-format annual network actuals for Anaplan or Jedox: version, promotion, line item, value."""
    t, _ = finance.network_pnl()
    if t.empty:
        return ""
    items = {"incremental_sales": "Incremental Sales", "incremental_margin": "Incremental Gross Margin",
             "discount_cost": "Discount Cost", "compute_cost": "Databricks Compute", "platform_cost": "Platform Cost",
             "operating_profit": "Operating Profit Impact", "capital": "Capital Deployed", "roic": "ROIC"}
    long = t.melt(id_vars=["promotion_id"], value_vars=list(items), var_name="line_item", value_name="value")
    long["line_item"] = long.line_item.map(items)
    long.insert(0, "version", "Actual, annualized")
    long.insert(0, "period", f"FY{datetime.now(timezone.utc):%Y}")
    long["value"] = long.value.astype(float).round(4)
    return long.to_csv(index=False)


# ---------------------------------------------------------------------------
# Approvals and the AI/BI dashboard
# ---------------------------------------------------------------------------

def _proposal_id(r):
    return f"{datetime.now(timezone.utc):%Y-%m-%d}-{r['promotion_id']}-{r['kind']}"


def proposal_status(r):
    """proposed, approved or rejected. Session first, then agent_proposals."""
    pid = _proposal_id(r)
    decided = st.session_state.setdefault("_decisions", {})
    if pid in decided:
        return decided[pid]
    if not data.LOCAL:
        try:
            rows = data._query(f"SELECT status FROM {data.SCHEMA}.agent_proposals WHERE proposal_id = :p "
                               f"ORDER BY created_at DESC LIMIT 1", {"p": pid})
            if not rows.empty and rows.status.iloc[0]:
                return rows.status.iloc[0]
        except Exception:
            pass
    return "proposed"


def decide_proposal(r, status):
    """Record the decision in agent_proposals and, if approved, the change in promotion_changes."""
    pid, now, user = _proposal_id(r), _now(), data.current_user()
    st.session_state.setdefault("_decisions", {})[pid] = status
    if not data.LOCAL:
        try:
            data._query(f"UPDATE {data.SCHEMA}.agent_proposals SET status = :s, decided_by = :u, "
                        f"decided_at = CAST(:t AS TIMESTAMP) WHERE proposal_id = :p",
                        {"s": status, "u": user, "t": now, "p": pid})
        except Exception as e:
            st.toast(f"Approval write skipped: {str(e).splitlines()[0][:120]}")
    if status == "approved":
        data.append_rows("promotion_changes", [{
            "change_id": str(uuid.uuid4()), "promotion_id": r["promotion_id"], "change_type": r["kind"],
            "field": None, "old_value": None, "new_value": r["title"], "reason": r["why"],
            "source": "agent, approved", "changed_by": user, "changed_at": now}])
    record_activity("approval", f"{status}: {r['title']}")


@st.cache_data(ttl=600)
def dashboard_urls():
    """(open URL, embed URL) of the published AI/BI dashboard, found by name. Empty strings if not found."""
    name = os.getenv("NBO_DASHBOARD_NAME", "NBO Offer Engine")
    if data.LOCAL:
        return "", ""
    try:
        w = data._workspace()
        host = w.config.host.rstrip("/")
        for d in w.lakeview.list():
            if name.lower() in (d.display_name or "").lower():
                return (f"{host}/dashboardsv3/{d.dashboard_id}/published",
                        f"{host}/embed/dashboardsv3/{d.dashboard_id}")
    except Exception:
        pass
    return "", ""
