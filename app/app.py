import html
import os
import time

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

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
        .block-container { padding-top: 1.5rem !important; padding-bottom: 1.5rem !important; }
        .phone { border: 2px solid #222; border-radius: 22px; padding: 14px 14px 18px; max-width: 300px;
                 background: #fafafa; }
        .phone .bar { font-size: 11px; color: #666; display: flex; justify-content: space-between; }
        .phone .push { margin-top: 10px; background: #fff; border-radius: 12px; padding: 10px 12px;
                       box-shadow: 0 1px 4px rgba(0,0,0,.15); }
        .phone .push .app { font-size: 11px; color: #008060; font-weight: 600; }
        .phone .push .msg { font-size: 14px; font-weight: 600; margin-top: 2px; }
        .pinpad { border: 2px solid #222; border-radius: 8px; background: #111; color: #eee; padding: 12px;
                  max-width: 300px; margin-top: 10px; font-family: monospace; font-size: 12.5px; }
        .pinpad .hl { color: #7CFC9A; }
        .muted { color: #888; }
        .phone .loc { font-size: 11.5px; margin-top: 8px; color: #0a66c2; }
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
    name = html.escape(shopper_name(prof).split(" ")[0])
    loc = (f'<div class="loc">Location shared · entered the store at {ts:%H:%M}</div>' if dec is not None and dec.app_user
           else '<div class="loc muted">No app location: loyalty ID scanned at the pin-pad</div>')
    if dec is not None and dec.decision == "Offer served":
        msg = html.escape(dec.offer_message)
        phone = (f'<div class="push"><div class="app">7-ELEVEN · now</div>'
                 f'<div class="msg">{msg}</div><div class="muted">Tap to add to your order</div></div>'
                 if dec.app_user else '<div class="push muted">Not an app user: pin-pad only</div>')
        pin = f'<div class="pinpad">HI {name.upper()}!<br><span class="hl">{msg.upper()}</span><br>[ ADD ]  [ NO THANKS ]</div>'
    else:
        reason = "HELD OUT FOR MEASUREMENT" if dec is not None and dec.holdout else "NO OFFER"
        phone = f'<div class="push muted">No notification sent ({reason.lower()})</div>'
        pin = f'<div class="pinpad">HI {name.upper()}!<br>SCAN YOUR ITEMS<br><span class="muted">{reason}</span></div>'
    if dec is None or not dec.app_user:
        return f'<div class="loc muted">No app: loyalty ID scanned at the pin-pad</div>{pin}'
    return (f'<div class="phone"><div class="bar"><span>{ts:%H:%M}</span><span>5G</span></div>{loc}{phone}</div>'
            f'{pin}')


PERMISSION_PROMPT = """<div class="phone"><div class="bar"><span>7-Eleven app</span><span>5G</span></div>
<div class="push"><div class="msg">Allow “7-Eleven” to use your location?</div>
<div class="muted">We'll send you deals the moment you walk into a store.</div>
<div style="margin-top:8px;font-weight:600;color:#0a66c2">Allow While Using App<br>Allow Once<br>Don't Allow</div></div></div>"""


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

st.title("Real-Time Next Best Offer")
st.markdown("While a shopper is in the store, the system picks the promotion most likely to get that person to "
            "add to their basket and sends it to them right then.")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "1. In-Store Live",
    "2. Decision Trace",
    "3. Under the Hood",
    "4. Does the Model Work?",
    "5. Ask Genie",
])

# ==========================================
# 1. IN-STORE LIVE
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
            st.subheader(f"{last['time']:%H:%M} · {shopper_name(prof)} walked in")
            st.markdown(offer_card(dec, prof, last["time"]), unsafe_allow_html=True)
        with right:
            st.subheader("What the decision path saw")
            ev = events[events.event_id == last["event_id"]].iloc[0]
            st.markdown(
                f"- **Signal:** {ev.trigger} at store {store_id} ({ev.daypart.lower()})\n"
                f"- **Already scanned:** {ev.first_scan_label}\n"
                f"- **Days since last visit:** {ev.days_since_prev_visit if ev.days_since_prev_visit < 999 else 'first visit'}\n"
                f"- **Decision:** {dec.decision}"
                + (f" → **{PROMOS.at[dec.promotion_id, 'short_name']}**" if dec.decision == "Offer served" else "")
                + f"\n- **Why:** {dec.reason}\n"
                f"- **Decided by:** {last['served_by']}, {last['latency_ms']:.0f} ms round trip")
            if dec.decision == "Offer served":
                st.success(f"Likelihood to buy moves from {pct(dec.p_without_offer)} to {pct(dec.p_with_offer)} "
                           f"with the offer. Expected net margin ${dec.expected_net_margin:.2f}.")
            if last.get("_payload"):
                st.markdown(f"**iOS push:** {last['push']}")
                with st.expander("Push payload (APNs format)"):
                    st.json(last["_payload"])
            st.caption(f"Open event {last['event_id']} in **Decision Trace** to see every offer it scored.")

        st.subheader("Decision stream")
        feed = log.drop(columns=["_dec", "_payload", "store_id", "promotion_id", "served_by"]).iloc[::-1]
        feed["time"] = feed.time.dt.strftime("%H:%M")
        st.dataframe(
            feed[["time", "event_id", "member_id", "trigger", "first_scan", "decision", "offer", "push",
                  "latency_ms", "reason"]],
            column_config={"latency_ms": st.column_config.NumberColumn("ms", format="%.1f"),
                           "event_id": st.column_config.NumberColumn("Event", format="%d"),
                           "member_id": st.column_config.NumberColumn("Member", format="%d")},
            hide_index=True, width="stretch", height=300)
        st.caption("Every decision is appended to `live_decision_log` in Unity Catalog, next to the full-day "
                   "`offer_decisions` table written by the streaming decision job.")


# ==========================================
# 2. DECISION TRACE
# ==========================================
with tab2:
    st.header("Decision Trace")
    st.caption("One check-in, end to end: the event, the features looked up for the shopper, every promotion "
               "scored, the live rules, and the payload sent to the app and pin-pad.")

    featured = data.table("featured_events")
    f1, f2 = st.columns([2, 1])
    pick = f1.selectbox("Pick a check-in", featured.display.tolist())
    typed = f2.text_input("…or an event ID from the live stream", placeholder="from the decision stream")
    event_id = int(featured.set_index("display").at[pick, "event_id"])
    if typed.strip():
        try:
            event_id = int(typed.strip().lstrip("#"))
        except ValueError:
            st.error("Event IDs are numbers.")
    ev, sc, pr = data.event_bundle(event_id)

    if ev is None:
        st.warning(f"No event {event_id}.")
    else:
        e = ev.iloc[0]
        prof = pr.iloc[0] if len(pr) else None
        dec, cand, ms = run_decision(e, sc, pr if len(pr) else pd.DataFrame({"member_id": [e.member_id],
                                                                              "marketing_opt_in": [False]}))

        s1, s2, s3 = st.columns([1, 1, 1.1])
        with s1:
            st.subheader("1. Event in")
            st.json({"event_id": int(e.event_id), "ts": f"{e.event_ts:%Y-%m-%d %H:%M}",
                     "member_id": int(e.member_id), "store_id": int(e.store_id), "trigger": e.trigger,
                     "daypart": e.daypart, "first_scan": e.first_scan_label,
                     "days_since_prev_visit": int(e.days_since_prev_visit),
                     "store_has_fresh_bakery": bool(e.store_has_fresh_bakery)}, expanded=True)
        with s2:
            st.subheader("2. Features looked up")
            if prof is not None:
                st.markdown(
                    f"- **{shopper_name(prof)}**, {prof.crm_segment}, {prof.tenure_months} months\n"
                    f"- {prof.visits_per_active_week:.1f} visits per active week, avg basket "
                    f"${prof.avg_basket_value:.2f}\n"
                    f"- Coffee on {pct(prof.coffee_rate)} of visits; pastry on "
                    f"{pct(prof.pastry_with_coffee_rate)} of coffee visits\n"
                    f"- Visit mix: {pct(prof.morning_share)} morning · {pct(prof.midday_share)} midday · "
                    f"{pct(prof.afternoon_share)} afternoon · {pct(prof.late_night_share)} late night\n"
                    f"- {'App user' if prof.app_user else 'No app'} · "
                    f"{'opted in' if prof.marketing_opt_in else 'not opted in'}")
            st.caption("From `member_features`, published to the online feature store. The endpoint reads them "
                       "by `member_id` in milliseconds; the caller sends only the check-in.")
        with s3:
            st.subheader("3. Offer sent")
            st.markdown(offer_card(dec, prof, e.event_ts), unsafe_allow_html=True)

        st.subheader("4. Every promotion scored for this moment")
        cv = cand.copy()
        cv["Promotion"] = cv.promotion_id.map(PROMOS.short_name)
        cv["Live rule"] = cv.context_rule + np.where(cv.context_ok, " (met)", " (not met)")
        cv["Decision"] = np.select(
            [cv.promotion_id.eq(dec.promotion_id) & (dec.decision == "Offer served"),
             cv.promotion_id.eq(dec.promotion_id) & dec.holdout,
             ~cv.eligible, ~cv.context_ok, cv.tier != "Persuadable"],
            ["Sent", "Holdout: logged, not shown", "Not eligible", "Doesn't fit this moment",
             "Suppressed (" + cv.tier + ")"], default="Lower margin than winner")
        for col in ["p_with_offer", "p_without_offer", "uplift"]:
            cv[col] = cv[col] * 100
        st.dataframe(
            cv.sort_values("expected_net_margin", ascending=False)[
                ["Promotion", "Live rule", "p_without_offer", "p_with_offer", "uplift", "expected_net_margin",
                 "tier", "Decision"]],
            column_config={
                "p_with_offer": st.column_config.ProgressColumn("Buys with offer", format="%.0f%%", min_value=0,
                                                                max_value=100),
                "p_without_offer": st.column_config.NumberColumn("Buys without", format="%.0f%%"),
                "uplift": st.column_config.NumberColumn("Lift", format="%.0f pts"),
                "expected_net_margin": st.column_config.NumberColumn("Net margin", format="dollar"),
                "tier": "Model tier",
            },
            hide_index=True, width="stretch")
        st.info(f"**Decision:** {dec.decision}. {dec.reason}.")
        sdec, sms, served_by, req, resp = serve_decision(e, sc, pr if len(pr) else
                                                         pd.DataFrame({"member_id": [e.member_id],
                                                                       "marketing_opt_in": [False]}))
        r1, r2 = st.columns(2)
        with r1:
            st.markdown(f"**Request to the decision service** ({served_by})")
            st.json({"dataframe_records": [req]}, expanded=True)
        with r2:
            st.markdown(f"**Response** · {sms:.0f} ms round trip")
            st.json({k: (v.item() if hasattr(v, "item") else v) for k, v in (resp or {}).items()}, expanded=True)
        st.caption("The endpoint looks up the shopper's features online by `member_id`, scores both response "
                   "models for every promotion, and applies the live rules in `nbo_decision.py`: the same code the "
                   "streaming job and this table use.")


# ==========================================
# 3. UNDER THE HOOD
# ==========================================
with tab3:
    st.header("Under the Hood")
    st.caption("The hard parts: streaming in-store signals, serving features with low latency, scoring models in "
               "milliseconds, and governing all of it on Databricks.")

    st.graphviz_chart("""
digraph {
  rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#F4F6F7", fontname="Helvetica", fontsize=11];
  edge [fontname="Helvetica", fontsize=9, color="#888"];
  app [label="7-Eleven app\\nshared location:\\nentered store"]; pos [label="POS pin-pad\\nloyalty ID scan"];
  zb [label="Zerobus ingest", fillcolor="#FFE8D6"];
  bronze [label="instore_events\\n(Delta, streaming)"];
  sdp [label="Lakeflow job\\nmember_features", fillcolor="#FFE8D6"];
  online [label="Online feature store\\n(Lakebase, CONTINUOUS sync)", fillcolor="#FFE8D6"];
  ml [label="MLflow + UC registry\\nnbo_decision_service @prod", fillcolor="#FFE8D6"];
  ep [label="Model Serving endpoint\\nnbo-decision\\nlookup + score + rules", fillcolor="#D5F5E3"];
  push [label="Push notification\\n+ pin-pad offer", fillcolor="#D5F5E3"];
  inf [label="Inference table\\nnbo_decision_payload"];
  dash [label="AI/BI dashboard\\n+ Genie"];
  uc [label="Unity Catalog: lineage, row filters,\\nPII masks, endpoint permissions", shape=note, fillcolor="#EBF5FB"];
  app -> ep [label="check-in (REST)"]; pos -> ep; app -> zb; pos -> zb; zb -> bronze;
  bronze -> sdp [label="stream"]; sdp -> online; online -> ep [label="key lookup"];
  ml -> ep [label="serves"]; ep -> push [label="offer"]; ep -> inf; inf -> dash; bronze -> dash;
  inf -> ml [label="retrain on holdout"];
}""", width="stretch")

    st.subheader("Latency budget: check-in to offer on screen")
    budget = pd.DataFrame([
        {"Step": "Check-in reaches the endpoint (app or pin-pad → REST)", "Target": "< 100 ms", "Runs on": "Model Serving"},
        {"Step": "Feature lookup by member_id", "Target": "< 10 ms", "Runs on": "Online feature store (Lakebase)"},
        {"Step": "Score 2 response models × 5 promotions", "Target": "< 30 ms", "Runs on": "nbo_decision_service"},
        {"Step": "Live rules + arbitration + 10% holdout", "Target": "< 5 ms", "Runs on": "nbo_decision.py"},
        {"Step": "Push notification and pin-pad offer", "Target": "< 300 ms", "Runs on": "Push service / POS API"},
        {"Step": "Request + response logged", "Target": "async", "Runs on": "Inference table (AI Gateway)"},
        {"Step": "Check-in event streamed to Delta", "Target": "seconds", "Runs on": "Zerobus → instore_events"},
    ])
    st.dataframe(budget, hide_index=True, width="stretch")
    log = pd.DataFrame(st.session_state.get("live_log", []))
    if len(log):
        st.caption(f"Measured in this app session: {len(log):,} decisions, round trip p50 "
                   f"{np.percentile(log.latency_ms, 50):.0f} ms, p95 {np.percentile(log.latency_ms, 95):.0f} ms "
                   f"({data.endpoint_label()}).")

    st.subheader("Tables behind the decision path")
    objs = [
        ("instore_events", "Bronze", "Check-in stream: member, store, trigger, daypart, first item scanned"),
        ("pos_baskets", "Bronze", "12 months of POS baskets with category flags"),
        ("offer_history", "Bronze", "Every in-store offer Jan–Sep 2026, with its 10% holdout"),
        ("member_features", "Silver / online", "Visit mix, category rates, recency per member; published online"),
        ("member_offer_scores", "Gold", "Member × promotion: buys with and without offer, lift, net margin, tier (nightly)"),
        ("offer_decisions", "Gold", "One decision per check-in, written by the streaming decision job"),
        ("nbo_decision_payload", "Gold", "Every request and response to the nbo-decision endpoint"),
        ("live_decision_log", "Gold", "Decisions made from this app"),
        ("tier_backtest", "Gold", "Measured lift by model tier on the holdout"),
    ]
    counts = data.table_counts(tuple(o[0] for o in objs))
    st.dataframe(pd.DataFrame([{"Table": n, "Layer": l, "Rows": counts.get(n), "What it holds": d}
                               for n, l, d in objs]),
                 column_config={"Rows": st.column_config.NumberColumn(format="%d")},
                 hide_index=True, width="stretch")
    st.caption("Governance: regional analysts see only their region's rows (row filter on `region`); first name, "
               "last name, and email are masked unless you are in `nbo_pii_readers`. The app runs as its own "
               "service principal with the same rules.")


# ==========================================
# 4. DOES THE MODEL WORK?
# ==========================================
with tab4:
    st.header("Does the Model Work?")
    st.caption("Every in-store offer holds back 10% of shoppers. Comparing the two groups shows what each offer "
               "really caused, and whether the model's tiers hold up.")

    bt = data.table("tier_backtest")
    bt = bt.merge(PROMOS[["short_name"]], left_on="promotion_id", right_index=True)
    bt = bt[bt.holdout_sends >= 30]
    st.subheader("Measured lift by model tier, Apr–Sep in-store offers")
    chart = alt.Chart(bt).mark_bar().encode(
        x=alt.X("tier:N", title=None, sort=BACKTEST_TIERS),
        y=alt.Y("measured_uplift:Q", title="Offer minus holdout conversion", axis=alt.Axis(format="%")),
        color=alt.Color("tier:N", legend=None,
                        scale=alt.Scale(domain=BACKTEST_TIERS, range=["#008060", "#9AA5A8", "#FF6600", "#C0392B"])),
        column=alt.Column("short_name:N", title=None),
        tooltip=["short_name", "tier", alt.Tooltip("measured_uplift:Q", format=".1%"),
                 alt.Tooltip("treatment_sends:Q", format=","), alt.Tooltip("holdout_sends:Q", format=",")],
    ).properties(width=150, height=220)
    st.altair_chart(chart)
    st.caption("Shoppers the model calls Persuadable buy far more when they get the offer. Sure Things buy the "
               "same either way, so the decision path suppresses them.")

    st.subheader("Why a model and not static rules")
    monthly = data.table("promo_monthly")
    monthly["month_end"] = pd.to_datetime(monthly.month_end)
    monthly["month_end"] = monthly.month_end.dt.to_period("M").dt.start_time  # plot each month at its start
    trend = (monthly.groupby("month_end")[["discount_cost", "incremental_margin"]].sum().reset_index()
             .melt("month_end", var_name="measure", value_name="usd"))
    trend["measure"] = trend.measure.map({"discount_cost": "Discount spend",
                                          "incremental_margin": "Incremental margin (vs holdout)"})
    lines = alt.Chart(trend).mark_line(point=True).encode(
        x=alt.X("month_end:T", title=None, axis=alt.Axis(format="%b %Y", tickCount={"interval": "month", "step": 1})),
        y=alt.Y("usd:Q", title="USD"),
        color=alt.Color("measure:N", title=None, scale=alt.Scale(range=["#FF6600", "#008060"]),
                        legend=alt.Legend(orient="bottom")),
        tooltip=[alt.Tooltip("month_end:T", format="%b %Y"), "measure", alt.Tooltip("usd:Q", format="$,.0f")],
    )
    pre = monthly[monthly.month_end < "2026-04-01"].month_end.max()
    post = monthly[monthly.month_end >= "2026-04-01"].month_end.min()
    change_x = pre + (post - pre) / 2
    rule = alt.Chart(pd.DataFrame({"x": [change_x]})).mark_rule(strokeDash=[4, 4], color="#888").encode(x="x:T")
    label = alt.Chart(pd.DataFrame({"x": [change_x], "t": ["Apr 1: static rules, every eligible offer"]})).mark_text(
        align="right", dx=-6, dy=6, color="#666").encode(x="x:T", y=alt.value(0), text="t")
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#ccc").encode(y="y:Q")
    st.altair_chart((zero + lines + rule + label).properties(height=260), width="stretch")

    pf = data.table("promo_portfolio")
    view = pf[["short_name", "eligible_members", "persuadable_members", "redemption_rate_apr_sep",
               "measured_uplift_apr_sep", "blast_net_margin_per_send", "targeted_net_margin_per_send"]].copy()
    view["redemption_rate_apr_sep"] *= 100
    view["measured_uplift_apr_sep"] *= 100
    st.dataframe(
        view,
        column_config={
            "short_name": "Promotion",
            "eligible_members": st.column_config.NumberColumn("Eligible shoppers", format="%d"),
            "persuadable_members": st.column_config.NumberColumn("Persuadable", format="%d"),
            "redemption_rate_apr_sep": st.column_config.NumberColumn("Redemption rate", format="%.0f%%"),
            "measured_uplift_apr_sep": st.column_config.NumberColumn("Measured lift", format="%.1f pts"),
            "blast_net_margin_per_send": st.column_config.NumberColumn("Net margin / month: static rules",
                                                                       format="dollar"),
            "targeted_net_margin_per_send": st.column_config.NumberColumn("Net margin / month: model",
                                                                          format="dollar"),
        },
        hide_index=True, width="stretch")
    hero = pf.set_index("promotion_id").loc["PR01"]
    st.info(f"Static rules show Coffee + Croissant to every eligible morning shopper: "
            f"{pct(hero.redemptions_that_would_happen_anyway)} of redemptions would have happened anyway and it "
            f"loses {money(-hero.blast_net_margin_per_send)} a month on the pilot. Scored per shopper in real time, "
            f"it earns {money(hero.targeted_net_margin_per_send)}. Across all offers that is "
            f"{money(pf.annual_gain_vs_blast.sum())} a year on 25,000 members, scaling with members.")

# ==========================================
# SCREEN 5: ASK GENIE
# ==========================================
with tab5:
    st.header("Ask Genie")
    st.caption("Plain-English questions over the same governed metric view, decision tables, and inference table the "
               "dashboard reads.")

    if not data.genie_enabled():
        st.info("Genie isn't connected to this app yet. Set `GENIE_SPACE_ID` in app.yaml to turn this on. "
                "On a local preview, ask in the Genie space in the workspace instead.")
    else:
        examples = [
            "How many check-ins got an offer today, and why did the rest not?",
            "Which offers did we push, by daypart?",
            "What is the endpoint's p95 latency?",
            "Does the model's tiering hold up against the holdout?",
        ]
        q_pick = st.selectbox("Example questions", ["Type your own", *examples])
        question = st.text_input("Question", value="" if q_pick == "Type your own" else q_pick)
        if st.button("Ask", type="primary", disabled=not question.strip()):
            with st.spinner("Genie is working..."):
                try:
                    answer = data.ask_genie(question.strip())
                except Exception as e:  # surface the reason instead of a stack trace
                    st.error(f"Genie request failed: {str(e).splitlines()[0]}")
                    answer = None
            if answer:
                for text in answer["texts"]:
                    st.markdown(text)
                for res in answer["queries"]:
                    if res.get("description"):
                        st.markdown(f"**{res['description']}**")
                    if res.get("frame") is not None:
                        st.dataframe(res["frame"], hide_index=True, width="stretch")
                    if res.get("sql"):
                        with st.expander("SQL Genie ran"):
                            st.code(res["sql"], language="sql")
