import html

import altair as alt
import pandas as pd
import streamlit as st

import agent
import data
import finance

st.set_page_config(page_title="Offer Engine", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
  [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none; }
  header[data-testid="stHeader"] { background: transparent; }
  .block-container { padding-top: 1.4rem !important; padding-bottom: 6rem !important; max-width: 1360px; }
  .eyebrow { font-size: 12px; letter-spacing: .14em; font-weight: 700; color: #FF5F46; text-transform: uppercase; }
  .ptitle { font-size: 30px; font-weight: 700; color: #F9F7F4; line-height: 1.15; }
  .bell { display:inline-flex; align-items:center; gap:8px; font-size:13px; color:#C9D2D5; justify-content:flex-end; width:100% }
  .bell b { background:#FF3621; color:#fff; border-radius:999px; padding:1px 8px; font-size:12px; }
  .kpi { background:#11262D; border:1px solid #1F3A43; border-radius:12px; padding:16px 18px; }
  .kpi .l { font-size:12.5px; color:#9AA9AE; }
  .kpi .v { font-size:30px; font-weight:700; color:#F9F7F4; line-height:1.15; margin-top:6px; }
  .kpi .s { margin-top:8px; }
  .sec { font-size:13px; font-weight:600; color:#C9D2D5; margin:26px 0 10px; }
  .sc { background:#11262D; border:1px solid #1F3A43; border-radius:12px; overflow:hidden; margin-bottom:6px; }
  .sc .bar { height:5px; }
  .sc .in { padding:16px 18px 6px; }
  .sc h4 { font-size:17px; font-weight:700; color:#F9F7F4; margin:0 0 4px; padding:0; }
  .sc .d { font-size:13px; color:#9AA9AE; min-height:38px; }
  .strip { display:grid; grid-template-columns:repeat(3,1fr); background:#0B2026; border:1px solid #1F3A43;
           border-radius:10px; margin:12px 0; }
  .strip div { text-align:center; padding:10px 4px; border-right:1px solid #1F3A43; }
  .strip div:last-child { border-right:none; }
  .strip span { display:block; font-size:11.5px; color:#9AA9AE; }
  .strip b { font-size:19px; color:#F9F7F4; }
  .strip b.g { color:#00A972; } .strip b.r { color:#FF5F46; }
  .tags { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; font-size:11.5px; color:#9AA9AE; }
  .tags .lb { display:block; border-bottom:1px solid #1F3A43; padding-bottom:6px; margin-bottom:8px; }
  .pill { display:inline-block; font-size:12px; font-weight:600; padding:3px 10px; border-radius:999px;
          background:#1B3139; color:#C9D2D5; }
  .pill.good { background:rgba(0,169,114,.16); color:#2FD39A; }
  .pill.warn { background:rgba(254,171,3,.16); color:#FEC44D; }
  .pill.bad { background:rgba(255,54,33,.16); color:#FF7A66; }
  .ai { font-size:12.5px; color:#9AA9AE; border-top:1px solid #1F3A43; padding:10px 0 4px; margin-top:12px; }
  .ai b { color:#C9D2D5; }
  .st-key-agent_fab { position: fixed; right: 28px; bottom: 24px; z-index: 999; width: auto !important; }
  .st-key-agent_fab button { border-radius: 999px; padding: 0.6rem 1.2rem; background:#1B3139; border:1px solid #1F3A43;
                             box-shadow: 0 6px 18px rgba(0,0,0,.35); }
</style>
""", unsafe_allow_html=True)

def hurdle_now():
    return finance.assumptions()["hurdle_rate"]


KIND_COLOR = {"Scale": "#00A972", "Retarget": "#FEAB03", "Stop or switch": "#FF3621"}


def kpi(col, label, value, pill=""):
    col.markdown(f'<div class="kpi"><div class="l">{label}</div><div class="v">{value}</div>'
                 f'<div class="s">{pill}</div></div>', unsafe_allow_html=True)


def scenario_card(r, prog, hurdle):
    """One agent action as a scenario card: what it changes, the numbers, the status, the AI's reason."""
    roic = prog.roic if prog is not None else None
    met = roic is not None and roic >= hurdle
    enough = prog is not None and bool(prog.enough_data)
    roic_txt = f"{roic:.1%}" if roic is not None and enough else "–"
    acc_txt = f"{prog.acceptance_rate:.0%}" if prog is not None and prog.acceptance_rate == prog.acceptance_rate else "–"
    conf = ('<span class="pill good">High</span>' if enough else '<span class="pill warn">Low</span>')
    cost = agent.money(prog.discount_cost) if prog is not None else "$0"
    thr = (f'<span class="pill good">Met</span>' if met else '<span class="pill bad">Below</span>') if enough else \
        '<span class="pill">Too early</span>'
    return (f'<div class="sc"><div class="bar" style="background:{KIND_COLOR.get(r["kind"], "#618693")}"></div>'
            f'<div class="in"><h4>{html.escape(r["title"])}</h4><div class="d">{html.escape(r["kind"])}</div>'
            f'<div class="strip"><div><span>Profit / yr</span><b class="g">{agent.money(r["impact"], True)}</b></div>'
            f'<div><span>Program ROIC</span><b class="{"g" if met else "r"}">{roic_txt}</b></div>'
            f'<div><span>Acceptance</span><b>{acc_txt}</b></div></div>'
            f'<div class="tags"><div><span class="lb">Confidence</span>{conf}</div><div><span class="lb">Discount / yr</span>'
            f'<span class="pill">{cost}</span></div><div><span class="lb">Hurdle</span>{thr}</div></div>'
            f'<div class="ai"><b>AI:</b> {html.escape(r["why"])}</div></div></div>')


def render_overview():
    b = agent.briefing()
    ft, fin = agent.finance_table()
    t, _ = finance.network_pnl()
    progs = t.set_index("promotion_id") if not t.empty else None
    pending = sum(agent.proposal_status(r) == "proposed" for r in b["recs"][:3])

    h1, h2, h3, h4 = st.columns([3.6, 1, 1.1, 1.1], vertical_alignment="center")
    h1.markdown('<div class="eyebrow">7-Eleven Offer Engine</div><div class="ptitle">Overview</div>',
                unsafe_allow_html=True)
    h2.markdown(f'<div class="bell">Approvals <b>{pending}</b></div>', unsafe_allow_html=True)
    if fin:
        if h3.download_button("Finance report", agent.finance_report_html(b, ft, fin),
                              file_name="offer-engine-finance-report.html", mime="text/html",
                              icon=":material/description:", width="stretch"):
            agent.record_activity("report", "Downloaded finance report")
        if h4.download_button("Export to EPM", agent.epm_export_csv(), file_name="offer-engine-actuals.csv",
                              mime="text/csv", icon=":material/upload_file:", width="stretch",
                              help="Actuals for Anaplan or Jedox"):
            agent.record_activity("export", "Exported actuals for EPM")

        st.write("")
        k = st.columns(4)
        gap = (fin["roic"] - fin["hurdle_rate"]) * 100
        kpi(k[0], "Incremental sales / yr", agent.money(fin["incremental_sales"]), '<span class="pill">Top line</span>')
        kpi(k[1], "Operating profit / yr", agent.money(fin["operating_profit"], True),
            '<span class="pill">Bottom line</span>')
        kpi(k[2], "ROIC", f"{fin['roic']:.1%}",
            f'<span class="pill {"good" if gap >= 0 else "bad"}">{gap:+.1f} pts vs {fin["hurdle_rate"]:.1%} hurdle</span>')
        kpi(k[3], "Compute per decision", f"${fin['cost_per_decision']:.5f}", '<span class="pill">Databricks</span>')

    if not t.empty:
        names = data.table("promotions").set_index("promotion_id").short_name
        c1, c2 = st.columns([1.25, 1])
        with c1.container(border=True):
            st.markdown('<div class="sec" style="margin-top:0">ROIC by offer program vs hurdle</div>',
                        unsafe_allow_html=True)
            d = t.assign(program=t.promotion_id.map(names),
                         status=t.apply(lambda r: "Too early" if not r.enough_data else
                                        ("Clears" if r.clears_hurdle else "Below"), axis=1))
            d = d[d.status != "Too early"]
            bars = alt.Chart(d).mark_bar(cornerRadiusEnd=4, height=22).encode(
                x=alt.X("roic:Q", title=None, axis=alt.Axis(format="%", grid=False)),
                y=alt.Y("program:N", sort="-x", title=None),
                color=alt.Color("status:N", scale=alt.Scale(domain=["Clears", "Below"],
                                range=["#00A972", "#FF3621"]), legend=alt.Legend(orient="bottom", title=None)),
                tooltip=["program", alt.Tooltip("roic:Q", format=".1%"), "status"])
            rule = alt.Chart(pd.DataFrame({"h": [hurdle_now()]})).mark_rule(color="#FEAB03", strokeDash=[4, 3]).encode(x="h:Q")
            st.altair_chart((bars + rule).properties(height=220, background="transparent"), width="stretch")
        with c2.container(border=True):
            st.markdown('<div class="sec" style="margin-top:0">Acceptance vs holdout by daypart</div>',
                        unsafe_allow_html=True)
            p = data.table("offer_performance").groupby("daypart")[["accepted", "delivered", "redeemed",
                                                                    "offers_served", "holdout_redeemed",
                                                                    "holdout_checkins"]].sum()
            dd = pd.DataFrame({"daypart": p.index,
                               "Redeemed with offer": p.redeemed / p.offers_served.clip(lower=1),
                               "Holdout": p.holdout_redeemed / p.holdout_checkins.clip(lower=1)}).melt(
                "daypart", var_name="group", value_name="rate")
            ch = alt.Chart(dd).mark_bar(cornerRadiusEnd=3).encode(
                x=alt.X("daypart:N", title=None, sort=["Morning", "Midday", "Afternoon", "Evening", "Late Night"],
                          axis=alt.Axis(labelAngle=0)),
                xOffset="group:N", y=alt.Y("rate:Q", title=None, axis=alt.Axis(format="%", grid=False)),
                color=alt.Color("group:N", scale=alt.Scale(range=["#618693", "#FF3621"]),
                                legend=alt.Legend(orient="bottom", title=None)),
                tooltip=["daypart", "group", alt.Tooltip("rate:Q", format=".1%")])
            st.altair_chart(ch.properties(height=220, background="transparent"), width="stretch")

    st.markdown('<div class="sec">Actions for approval</div>', unsafe_allow_html=True)
    agent.record_proposals(b["recs"])
    hurdle = fin.get("hurdle_rate", finance.assumptions()["hurdle_rate"])
    cols = st.columns(3)
    for i, r in enumerate(b["recs"][:3]):
        prog = progs.loc[r["promotion_id"]] if progs is not None and r["promotion_id"] in progs.index else None
        with cols[i]:
            st.markdown(scenario_card(r, prog, hurdle), unsafe_allow_html=True)
            status = agent.proposal_status(r)
            if status == "proposed":
                a1, a2, a3 = st.columns(3)
                if a1.button("Approve", key=f"ap_{i}", type="primary", width="stretch"):
                    agent.decide_proposal(r, "approved")
                    st.rerun()
                if a2.button("Reject", key=f"rj_{i}", width="stretch"):
                    agent.decide_proposal(r, "rejected")
                    st.rerun()
                if a3.button("Ask Genie", key=f"ask_rec_{i}", width="stretch"):
                    st.session_state["_open_chat"] = r["ask"]
            else:
                st.markdown(f'<span class="pill {"good" if status == "approved" else "bad"}">'
                            f'{status.capitalize()}</span>', unsafe_allow_html=True)

    st.markdown('<div class="sec">Offer programs</div>', unsafe_allow_html=True)
    if not t.empty:
        names = data.table("promotions").set_index("promotion_id").short_name
        t = t.sort_values("operating_profit", ascending=False)
        cols = st.columns(len(t))
        for c, (_, r) in zip(cols, t.iterrows()):
            ok, enough = bool(r.clears_hurdle), bool(r.enough_data)
            pill = (f'<span class="pill {"good" if ok else "bad"}">{"Clears hurdle" if ok else "Below hurdle"}</span>'
                    if enough else '<span class="pill warn">Too early to call</span>')
            c.markdown(
                f'<div class="sc"><div class="bar" style="background:{"#00A972" if ok and enough else "#FEAB03" if not enough else "#FF3621"}"></div>'
                f'<div class="in"><h4>{html.escape(str(names.get(r.promotion_id, r.promotion_id)))}</h4>{pill}'
                f'<div class="strip"><div><span>ROIC</span><b class="{"g" if ok else "r"}">'
                f'{f"{r.roic:.1%}" if enough else "–"}</b></div><div><span>Profit / yr</span>'
                f'<b>{agent.money(r.operating_profit, True)}</b></div><div><span>Accepted</span>'
                f'<b>{r.acceptance_rate:.0%}</b></div></div></div></div>', unsafe_allow_html=True)


def render_reporting():
    url, embed = agent.dashboard_urls()
    if embed:
        st.iframe(embed, height=1100) if hasattr(st, "iframe") else st.components.v1.iframe(embed, height=1100)
        st.link_button("Open in Databricks", url, icon=":material/open_in_new:")
    elif url:
        st.link_button("Open the AI/BI dashboard", url, type="primary", icon=":material/open_in_new:")
    else:
        st.info("The AI/BI dashboard appears here once the bundle deploys it.")


@st.dialog("Ask Genie", width="large")
def agent_chat(question=None):
    """The floating chat. Opens from the corner button on any tab, or from a recommendation."""
    ss = st.session_state
    ss.setdefault("chat", [])
    m = agent.mode()
    st.caption({"supervisor": f"Multi-Agent Supervisor `{agent.config()['endpoint']}`, routing to the Genie space",
                "genie": "Genie space (the supervisor isn't set up yet)",
                "local": "Local preview: answers come from the briefing",
                "none": "Not connected yet"}[m])
    box = st.container(height=420)
    with box:
        if not ss.chat:
            st.caption("Try: Which offer programs are below the hurdle? What should we change this week?")
        for msg in ss.chat:
            with st.chat_message(msg["role"]):
                if msg.get("routed"):
                    st.caption(f"Answered by: {msg['routed']}")
                st.markdown(msg["content"])
                for t in msg.get("tables", []) or []:
                    st.dataframe(t, hide_index=True, width="stretch")
                for q in msg.get("sql", []) or []:
                    with st.expander("SQL it ran"):
                        st.code(q, language="sql")
    with st.form("agent_ask", clear_on_submit=True, border=False):
        c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
        typed = c1.text_input("Ask the agent", placeholder="Ask a question or describe a change",
                              label_visibility="collapsed")
        sent = c2.form_submit_button("Ask", type="primary", width="stretch")
    q = question if question and not ss.get("_asked_" + question) else (typed.strip() if sent else "")
    if question:
        ss["_asked_" + question] = True
    if q:
        ss.chat.append({"role": "user", "content": q})
        with box:
            with st.chat_message("user"):
                st.markdown(q)
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    reply = agent.ask([{"role": x["role"], "content": x["content"]} for x in ss.chat])
                # Draw the reply in place: a fragment rerun is not allowed when the dialog was just opened
                if reply.get("routed"):
                    st.caption(f"Answered by: {reply['routed']}")
                st.markdown(reply["content"])
                for t in reply.get("tables", []) or []:
                    st.dataframe(t, hide_index=True, width="stretch")
                for sql in reply.get("sql", []) or []:
                    with st.expander("SQL it ran"):
                        st.code(sql, language="sql")
        ss.chat.append(reply)
        agent.record_activity("question", q, reply.get("routed", ""))
    if ss.chat and st.button("Clear conversation", type="tertiary"):
        ss.chat = []
        st.rerun(scope="fragment")



tab_overview, tab_reporting = st.tabs(["Overview", "Reporting"])
with tab_overview:
    render_overview()
with tab_reporting:
    render_reporting()

with st.container(key="agent_fab"):
    if st.button("Ask Genie", icon=":material/forum:", type="primary"):
        st.session_state["_open_chat"] = ""
# One dialog per run, whichever button opened it
if "_open_chat" in st.session_state:
    agent_chat(st.session_state.pop("_open_chat") or None)
