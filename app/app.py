import html
import os
import time

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import agent
import data
import nbo_decision as nd
import push

BRAND = os.getenv("NBO_BRAND", "7-Eleven")
st.set_page_config(page_title=f"{BRAND} · Real-Time Next Best Offer", layout="wide")

st.markdown("""
    <style>
        html, body, [class*="css"] { font-size: 13.5px !important; }
        h1 { font-size: 1.65rem !important; padding-bottom: 0.25rem !important; }
        h2 { font-size: 1.30rem !important; padding-top: 0.25rem !important; }
        h3 { font-size: 1.08rem !important; }
        [data-testid="stMetricValue"] { font-size: 1.35rem !important; }
        [data-testid="stMetricLabel"] { font-size: 0.85rem !important; }
        .block-container { padding-top: 1.5rem !important; padding-bottom: 5rem !important; }
        .phone { border: 2px solid #1B3139; border-radius: 22px; padding: 14px 14px 18px; max-width: 300px;
                 background: #FFFFFF; }
        .phone .bar { font-size: 11px; color: #4A5E68; display: flex; justify-content: space-between; }
        .phone .push { margin-top: 10px; background: #fff; border-radius: 12px; padding: 10px 12px;
                       box-shadow: 0 1px 4px rgba(0,0,0,.15); }
        .phone .push .app { font-size: 11px; color: #1B3139; font-weight: 600; }
        .phone .push .msg { font-size: 14px; font-weight: 600; margin-top: 2px; }
        .pinpad { border: 2px solid #0B2026; border-radius: 8px; background: #1B3139; color: #F9F7F4; padding: 12px;
                  max-width: 300px; margin-top: 10px; font-family: monospace; font-size: 12.5px; }
        .pinpad .hl { color: #00A972; }
        .muted { color: #4A5E68; }
        .phone .loc { font-size: 11.5px; margin-top: 8px; color: #1B5162; }
        .st-key-agent_fab { position: fixed; right: 28px; bottom: 24px; z-index: 999; width: auto !important; }
        .st-key-agent_fab button { border-radius: 999px; padding: 0.55rem 1.1rem; box-shadow: 0 4px 14px rgba(0,0,0,.18); }
    </style>
""", unsafe_allow_html=True)

PROMOS = data.table("promotions").set_index("promotion_id")
BACKTEST_TIERS = ["Persuadable", "Low ROI", "Sure Thing", "Lost Cause"]


def money(x, signed=False):
    sign = "+" if signed and x > 0 else ("-" if x < 0 else "")
    return f"{sign}${abs(x):,.0f}"


def pct(x, signed=False):
    return f"{x:+.0%}" if signed else f"{x:.0%}"


def shopper_name(prof):
    if prof is None or not isinstance(prof.first_name, str) or prof.first_name == "***":
        return "*** (PII masked)"
    return f"{prof.first_name} {prof.last_name[:1]}."


def run_decision(ev_row, scores, profiles):
    """The real-time decision path for one check-in. Returns (decision row, candidates, latency ms)."""
    t0 = time.perf_counter()
    ev = ev_row.to_frame().T.infer_objects()
    cand = nd.offer_candidates(ev, scores, profiles[["member_id", "marketing_opt_in"]])
    dec = nd.decide(cand).iloc[0] if len(cand) else None
    return dec, cand, (time.perf_counter() - t0) * 1000


def serve_decision(ev_row, scores, profiles):
    """Ask the real-time decision service; fall back to the in-app path if it is unavailable.
    Returns (decision Series, round-trip ms, served_by, request, response)."""
    req, resp, ms = data.call_decision_service(ev_row)
    if resp is not None:
        dec = pd.Series(resp)
        dec["app_user"] = bool(ev_row.app_user)
        dec["holdout"] = bool(dec.get("holdout", False))
        dec["promotion_id"] = dec.get("promotion_id") or None
        dec["offer_message"] = dec.get("offer_message") or None
        dec["channel"] = dec.get("channel") or None
        return dec, ms, data.endpoint_label(), req, resp
    dec, _, ms = run_decision(ev_row, scores, profiles)
    return dec, ms, "in-app fallback", req, None


def offer_card(dec, prof, ts):
    """Phone push and pin-pad screen for a decision."""
    loc = (f'<div class="loc">Location shared · entered the store at {ts:%H:%M}</div>' if dec is not None and dec.app_user
           else '<div class="loc muted">No app location: loyalty ID scanned at the pin-pad</div>')
    if dec is not None and dec.decision == "Offer served":
        msg = html.escape(dec.offer_message)
        phone = (f'<div class="push"><div class="app">7-ELEVEN · now</div>'
                 f'<div class="msg">{msg}</div><div class="muted">Tap to add to your order</div></div>'
                 if dec.app_user else '<div class="push muted">Not an app user: pin-pad only</div>')
        pin = f'<div class="pinpad">WELCOME BACK!<br><span class="hl">{msg.upper()}</span><br>[ ADD ]  [ NO THANKS ]</div>'
    else:
        reason = "HELD OUT FOR MEASUREMENT" if dec is not None and dec.holdout else "NO OFFER"
        phone = f'<div class="push muted">No notification sent ({reason.lower()})</div>'
        pin = f'<div class="pinpad">WELCOME BACK!<br>SCAN YOUR ITEMS<br><span class="muted">{reason}</span></div>'
    if dec is None or not dec.app_user:
        return f'<div class="loc muted">No app: loyalty ID scanned at the pin-pad</div>{pin}'
    return (f'<div class="phone"><div class="bar"><span>{ts:%H:%M}</span><span>5G</span></div>{loc}{phone}</div>'
            f'{pin}')


PERMISSION_PROMPT = """<div class="phone"><div class="bar"><span>7-Eleven app</span><span>5G</span></div>
<div class="push"><div class="msg">Allow “7-Eleven” to use your location?</div>
<div class="muted">We'll send you deals the moment you walk into a store.</div>
<div style="margin-top:8px;font-weight:600;color:#1B5162">Allow While Using App<br>Allow Once<br>Don't Allow</div></div></div>"""


with st.sidebar:
    st.markdown("**Data source**")
    st.caption(data.source_label())
    st.caption(f"Signed in as {data.current_user()}")
    st.divider()
    st.markdown("**Push to a phone**")
    st.caption(f"Push stack: {push.label()}")
    send_pushes = st.toggle("Send real pushes", value=push.configured(), disabled=not push.configured())
    st.caption("In production the retailer's app calls the endpoint when the shopper arrives, and their "
               "existing push stack delivers the offer. For the demo, offers can go to the ntfy app on a phone.")
    st.divider()
    st.caption("Live day 2026-09-30, replayed from the check-in stream. All shoppers, stores, and numbers "
               "are synthetic.")

def render_agent_tab():
    """Agent briefing: what's working, what isn't, and what to do next. Promotion level only."""
    b = agent.briefing()
    st.header("Offer agent")
    st.caption("The decision endpoint runs on every check-in in the background. The agent watches the results "
               "against the 10% holdout, tells you what's working and what isn't, and recommends what to change. "
               "Ask it anything with the button in the corner.")

    mix, lift, perf = b["mix"], b["lift"], b["perf"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Net margin a month, model targeting", agent.money(b["model_month"]),
              f"{agent.money(b['model_month'] - b['rules_month'], True)} vs static rules")
    if perf:
        k2.metric("Acceptance rate", f"{perf['acceptance_rate']:.0%}",
                  f"{perf['redemption_rate']:.0%} redeemed vs {perf['holdout_rate']:.0%} in holdout", delta_color="off")
        k3.metric("Return on spend", f"{perf['return_on_spend']:.0%}",
                  f"{agent.money(perf['net_return'], True)} net after discounts and compute", delta_color="off",
                  help=f"Net return / (discounts + compute). Compute is ${perf['cost_per_decision']:.5f} a decision.")
    k4.metric("Model check: measured lift", f"{lift['Persuadable'] * 100:+.0f} pts",
              f"{lift['Sure Thing'] * 100:+.0f} pts for shoppers it skips", delta_color="off")
    if mix:
        st.caption(f"Today: {mix['served']:.0%} of check-ins got an offer, {mix['no_offer']:.0%} needed none, "
                   f"{mix['holdout']:.0%} were held back to measure. Every decision and outcome is stored in "
                   f"Unity Catalog (`offer_outcomes`, `offer_performance`).")

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("What's working")
            for w in b["working"]:
                st.markdown(f":green[**{w['title']}.**] {w['detail']}")
    with right:
        with st.container(border=True):
            st.subheader("What isn't")
            for n in b["not_working"]:
                st.markdown(f":red[**{n['title']}.**] {n['detail']}")

    st.subheader("Recommendations")
    st.caption("Ranked by monthly margin. Changing an offer needs your approval; that comes in the next release.")
    for i, r in enumerate(b["recs"], 1):
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 1.2, 1.1], vertical_alignment="center")
            color = "red" if r["kind"] == "Stop or switch" else ("orange" if r["kind"] == "Retarget" else "green")
            c1.markdown(f"**{i}. {r['title']}**  \n:{color}[{r['kind']}] · {r['why']}")
            c2.metric("Margin a month", agent.money(r["impact"], True), label_visibility="visible")
            if c3.button("Ask the agent", key=f"ask_rec_{i}", width="stretch"):
                agent_chat(r["ask"])

    agent.record_proposals(b["recs"])
    st.caption("Promotion-level results only. Each recommendation is stored in `agent_proposals` for approval.")


@st.dialog("Offer agent", width="large")
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
            st.markdown("Ask what's working, what isn't, or what to change. For example:  \n"
                        "- *Which offers lose money, and why?*  \n"
                        "- *What should we change this week to raise margin?*  \n"
                        "- *How fast is the decision endpoint today?*")
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
        ss.chat.append(reply)
        agent.record_activity("question", q, reply.get("routed", ""))
        st.rerun(scope="fragment")
    if ss.chat and st.button("Clear conversation", type="tertiary"):
        ss.chat = []
        st.rerun(scope="fragment")


st.title("Real-Time Next Best Offer")
st.markdown("While a shopper is in the store, the system picks the promotion most likely to get that person to "
            "add to their basket and sends it to them right then.")

tab_agent, tab1 = st.tabs(["Agent", "In-Store Live"])

# ==========================================
# AGENT
# ==========================================
with tab_agent:
    render_agent_tab()

# ==========================================
# IN-STORE LIVE
# ==========================================
with tab1:
    st.header("In-Store Live")
    st.caption("Each check-in (the app's shared location says the shopper entered the store, or a loyalty ID scan "
               "at the pin-pad) is scored the moment it arrives. The shopper gets one offer, or none, while they "
               "are still in the aisle.")

    stores = data.stores_by_traffic()
    labels = [f"Store {r.store_id} · {r.city}, {r.region} · {r.check_ins} check-ins" for r in stores.itertuples()]
    c0, c1, c2, c3 = st.columns([2.2, 1, 1, 1])
    default_store = int(np.argmax(stores.has_fresh_bakery.astype(bool).to_numpy())) if len(stores) else 0
    pick = c0.selectbox("Store", labels, index=default_store)
    store_id = int(stores.store_id.iloc[labels.index(pick)])
    events, scores, profiles, fetch_ms = data.store_feed(store_id)
    prof_by_id = profiles.set_index("member_id")

    ss = st.session_state
    if ss.get("live_store") != store_id:
        ss.live_store, ss.live_pos, ss.live_log = store_id, 0, []
        # Start the replay just before the first morning offer, so the first clicks show a push
        day = nd.decide(nd.offer_candidates(events, scores, profiles[["member_id", "marketing_opt_in"]]))
        served = day[(day.decision == "Offer served") & day.app_user.astype(bool)
                     & (pd.to_datetime(day.event_ts).dt.hour >= 6)]
        hero = served[served.promotion_id == "PR01"]
        served = hero if len(hero) else served
        first = events.index[events.event_id == served.event_id.min()] if len(served) else events.index[:1]
        ss.live_pos = int(first[0]) if len(first) else 0

    def advance(n=None, minutes=None):
        start = ss.live_pos
        if minutes is not None:
            end_ts = events.event_ts.iloc[min(start, len(events) - 1)] + pd.Timedelta(minutes=minutes)
            stop = int((events.event_ts < end_ts).sum())
        else:
            stop = start + (n or 1)
        stop = min(max(stop, start + 1), len(events))
        new = []
        for i in range(start, stop):
            ev = events.iloc[i]
            dec, ms, served_by, _, _ = serve_decision(ev, scores, profiles)
            if dec is None:
                continue
            new.append({"event_id": int(ev.event_id), "store_id": store_id, "member_id": int(ev.member_id),
                        "time": ev.event_ts, "trigger": ev.trigger, "first_scan": ev.first_scan_label,
                        "decision": dec.decision, "promotion_id": dec.promotion_id,
                        "offer": dec.offer_message if dec.decision == "Offer served" else None,
                        "channel": dec.channel, "reason": dec.reason, "latency_ms": round(ms, 1),
                        "served_by": served_by, "_dec": dec})
            payload = nd.push_payload({**dec.to_dict(), "event_id": int(ev.event_id), "store_id": store_id}) \
                if dec.decision == "Offer served" and bool(ev.app_user) else None
            push_status, push_ms = push.send(payload, int(ev.member_id)) if (payload and send_pushes) else (
                "simulated" if payload else "no push", 0.0)
            new[-1].update({"push": push_status, "_payload": payload})
        ss.live_pos = stop
        ss.live_log = ss.live_log + new
        data.log_decisions([{k: v for k, v in r.items() if k not in ("_dec", "time", "trigger", "first_scan",
                                                                       "offer", "reason", "served_by", "push",
                                                                       "_payload")}
                            for r in new])

    done = ss.live_pos >= len(events)
    if c1.button("Next shopper walks in", type="primary", disabled=done, width="stretch"):
        advance(n=1)
    if c2.button("Play 15 minutes", disabled=done, width="stretch"):
        advance(minutes=15)
    st.caption(f"Decisions come from the {data.endpoint_label()}."
               + (f" Last error: {ss['endpoint_error']}" if ss.get("endpoint_error") else ""))
    if c3.button("Reset store", width="stretch"):
        ss.live_store = None
        st.rerun()

    log = pd.DataFrame(ss.live_log)
    k1, k2, k3, k4, k5 = st.columns(5)
    if len(log):
        served = (log.decision == "Offer served").sum()
        k1.metric("Check-ins decided", f"{len(log):,}")
        k2.metric("Offers served", f"{served:,}", f"{served / len(log):.0%} of check-ins", delta_color="off")
        k3.metric("Suppressed (no offer moves them)", f"{(log.decision == 'No offer').sum():,}")
        k4.metric("Held out (10%)", f"{(log.decision.str.startswith('Holdout')).sum():,}")
        k5.metric("Check-in → offer, p50 / p95", f"{np.percentile(log.latency_ms, 50):.0f} / "
                                                f"{np.percentile(log.latency_ms, 95):.0f} ms", delta_color="off")
    else:
        k1.metric("Check-ins decided", "0")
        k2.metric("Store clock", f"{events.event_ts.iloc[ss.live_pos]:%H:%M}" if not done else "end of day")
        k5.metric("Shopper data prefetch", f"{fetch_ms:,.0f} ms", "one query per store", delta_color="off")
        pc, tc = st.columns([1, 1.4])
        pc.markdown(PERMISSION_PROMPT, unsafe_allow_html=True)
        tc.markdown("**How a check-in fires.** The shopper shares their location with the 7-Eleven app once. "
                    "When they walk into a store, the app sends an *entered store* event with their loyalty ID. "
                    "That event is scored on the spot and the offer comes back as a push notification, and on the "
                    "pin-pad when they reach the counter. Shoppers without the app are scored when they scan "
                    "their loyalty ID at the pin-pad.")
        tc.info("Click **Next shopper walks in** to stream the first check-in through the decision path.")

    if len(log):
        last = ss.live_log[-1]
        dec = last["_dec"]
        prof = prof_by_id.loc[last["member_id"]] if last["member_id"] in prof_by_id.index else None
        st.divider()
        left, right = st.columns([1, 1.4])
        with left:
            seg = prof.crm_segment if prof is not None else "Loyalty shopper"
            st.subheader(f"{last['time']:%H:%M} · {seg} walked in")
            st.markdown(offer_card(dec, prof, last["time"]), unsafe_allow_html=True)
        with right:
            st.subheader("Decision")
            offer = (f" → **{PROMOS.at[dec.promotion_id, 'short_name']}**" if dec.decision == "Offer served" else "")
            st.markdown(f"**{dec.decision}**{offer} · {last['latency_ms']:.0f} ms · {last['served_by']}")
            if last.get("_payload"):
                st.markdown(f"**iOS push:** {last['push']}")
                with st.expander("Push payload (APNs format)"):
                    st.json(last["_payload"])

        st.subheader("Decision stream")
        feed = log.drop(columns=["_dec", "_payload", "store_id", "promotion_id", "served_by"]).iloc[::-1]
        feed["time"] = feed.time.dt.strftime("%H:%M")
        st.dataframe(
            feed[["time", "trigger", "first_scan", "decision", "offer", "push", "latency_ms"]],
            column_config={"latency_ms": st.column_config.NumberColumn("ms", format="%.1f")},
            hide_index=True, width="stretch", height=300)
        st.caption("Every decision is appended to `live_decision_log` in Unity Catalog, next to the full-day "
                   "`offer_decisions` table written by the streaming decision job.")


# ==========================================
# FLOATING AGENT BUTTON (every tab)
# ==========================================
with st.container(key="agent_fab"):
    if st.button("Ask the agent", icon=":material/forum:", type="primary"):
        agent_chat()
