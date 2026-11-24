"""The offer agent: the model's recommendations, approvals, the chat behind Ask Genie, and finance exports.

Recommendations are written to `agent_proposals` by the trained recommender (src/09_recommender.py). The app
reads them, and a person approves or rejects each one; every decision is stored in Unity Catalog
(`agent_proposals`, `promotion_changes`, `agent_activity`).

Chat: a Multi-Agent Supervisor (Agent Bricks) that routes questions to the Genie space over the same governed
tables. If no supervisor is set up yet, the chat asks the Genie space directly.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import data
import finance
from cache import ttl_cache

AGENT_NAME = "NBO Offer Agent"


def money(x, signed=False):
    """$12.4M, $310K, $950: the scale finance reads at."""
    sign = "+" if signed and x > 0 else ("-" if x < 0 else "")
    a = abs(x)
    body = f"{a / 1e9:.2f}B" if a >= 1e9 else f"{a / 1e6:.1f}M" if a >= 1e6 else f"{a / 1e3:.0f}K" if a >= 1e3 else f"{a:,.0f}"
    return f"{sign}${body}"


# ---------------------------------------------------------------------------
# Recommendations from the trained model, and decisions on them
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _proposals_frame():
    if data.LOCAL:
        path = Path(data.LOCAL_DIR) / "agent_proposals.csv"
        return pd.read_csv(path) if path.exists() else pd.DataFrame()
    return data._query(f"SELECT * FROM {data.SCHEMA}.agent_proposals WHERE model_name IS NOT NULL "
                       f"AND status <> 'superseded' ORDER BY scored_at DESC")


def _records(df):
    out = []
    for r in df.to_dict("records"):
        r = {k: (None if (not isinstance(v, (list, dict)) and pd.isna(v)) else v) for k, v in r.items()}
        try:
            r["evidence"] = json.loads(r.get("evidence") or "[]")
        except (TypeError, ValueError):
            r["evidence"] = [r["evidence"]] if r.get("evidence") else []
        for k in ("decided_at", "created_at", "scored_at", "proposal_date"):
            if r.get(k) is not None:
                r[k] = str(r[k])
        out.append(r)
    return out


def pending():
    """Open recommendations from the latest scoring run, highest expected profit first."""
    df = _proposals_frame()
    if df.empty or "model_name" not in df:
        return []
    df = df[df.model_name.notna() & (df.status == "proposed")]
    return _records(df.sort_values("expected_annual_profit_usd", ascending=False))


def decided(limit=10):
    df = _proposals_frame()
    if df.empty or "model_name" not in df:
        return []
    df = df[df.status.isin(["approved", "rejected"])].sort_values("decided_at", ascending=False).head(limit)
    return _records(df)


def all_current():
    df = _proposals_frame()
    if df.empty or "model_name" not in df:
        return []
    df = df[df.model_name.notna() & df.status.isin(["proposed", "approved", "rejected"])]
    return _records(df.sort_values("expected_annual_profit_usd", ascending=False))


def decide(proposal_id, status, reason=None):
    """Approve, reject, or undo (status='proposed') a recommendation. Writes agent_proposals, and for an
    approval or an undone approval, promotion_changes. Returns the updated recommendation."""
    if status not in ("approved", "rejected", "proposed"):
        raise ValueError("status must be approved, rejected or proposed")
    user, now = data.current_user(), _now()
    rows = [r for r in all_current() if r["proposal_id"] == proposal_id]
    if not rows:
        raise KeyError(proposal_id)
    r, before = rows[0], rows[0]["status"]
    who, when = (None, None) if status == "proposed" else (user, now)
    why = reason if status == "rejected" else None
    if data.LOCAL:
        path = Path(data.LOCAL_DIR) / "agent_proposals.csv"
        df = pd.read_csv(path)
        m = df.proposal_id == proposal_id
        df["decided_by"] = df["decided_by"].astype(object)
        df["decided_at"] = df["decided_at"].astype(object)
        df["reject_reason"] = df["reject_reason"].astype(object)
        df.loc[m, ["status", "decided_by", "decided_at", "reject_reason"]] = [status, who, when, why]
        df.to_csv(path, index=False)
    else:
        data._query(f"UPDATE {data.SCHEMA}.agent_proposals SET status = :s, decided_by = :u, "
                    f"decided_at = CAST(:t AS TIMESTAMP), reject_reason = :w WHERE proposal_id = :p",
                    {"s": status, "u": who, "t": when, "w": why, "p": proposal_id})
    if status == "approved" or before == "approved":
        data.append_rows("promotion_changes", [{
            "change_id": str(uuid.uuid4()), "promotion_id": r["promotion_id"],
            "change_type": r["action"] if status == "approved" else "reverted", "field": "targeting",
            "old_value": None, "new_value": r["title"], "reason": r["rationale"],
            "source": f"{r['model_name']} v{r['model_version']}, approved" if status == "approved" else "undo",
            "changed_by": user, "changed_at": now}])
    record_activity("decision", f"{status}: {r['title']}" + (f" ({reason})" if why else ""))
    r.update(status=status, decided_by=who, decided_at=when, reject_reason=why)
    return r


def record_activity(kind, content, routed=""):
    """Store a question asked of the agent (or a decision) in agent_activity."""
    try:
        data.append_rows("agent_activity", [{
            "activity_id": str(uuid.uuid4()), "activity_type": kind, "content": content[:2000],
            "routed_to": routed, "user_name": data.current_user(), "created_at": _now()}])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Chat: supervisor, Genie, local preview
# ---------------------------------------------------------------------------

@ttl_cache(60)
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
    """Local preview: answer from the stored recommendations so the chat can be tried without a workspace."""
    p = pending()
    lines = [f"- **{r['title']}.** {money(r['expected_annual_profit_usd'], True)} profit a year. "
             f"{'; '.join(r['evidence'])}." for r in p[:3]]
    return ("Local preview. On Databricks this goes to the supervisor and the Genie space.\n\n"
            "Top recommendations from the model:\n\n" + "\n".join(lines))


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
# Finance view: report and EPM export
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


def finance_report_html(t, total):
    b = pending()
    """One-page report for CFO sign-off, in the Databricks brand system."""
    import html as h
    a = finance.assumptions()
    rows = "".join(
        f"<tr><td>{h.escape(str(r.Promotion))}</td><td>{money(r['Incremental sales ($M/yr)'] * 1e6)}</td>"
        f"<td>{money(r['Operating profit ($M/yr)'] * 1e6, True)}</td><td>{r.ROIC:.1%}</td>"
        f"<td class='{'ok' if r['Clears hurdle'] else 'no'}'>{'Yes' if r['Clears hurdle'] else 'No'}</td></tr>"
        for _, r in t.iterrows())
    recs = "".join(f"<li><b>{h.escape(r['title'])}.</b> {money(r['expected_annual_profit_usd'], True)} a year. "
                   f"{h.escape('; '.join(r['evidence']))}</li>" for r in b)
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
# AI/BI dashboard
# ---------------------------------------------------------------------------

@ttl_cache(600)
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
