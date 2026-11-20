import altair as alt
import pandas as pd
import streamlit as st

import os

import data

BRAND = os.getenv("NBO_BRAND", "7-Eleven")
GREEN, ORANGE, RED = "#008163", "#F47B20", "#EE2526"

st.set_page_config(page_title=f"{BRAND} · Next Best Offer", page_icon="🏪", layout="wide")

st.markdown("""
    <style>
        html, body, [class*="css"] { font-size: 13.5px !important; }
        h1 { font-size: 1.65rem !important; padding-bottom: 0.25rem !important; }
        h2 { font-size: 1.30rem !important; padding-top: 0.25rem !important; }
        h3 { font-size: 1.08rem !important; }
        [data-testid="stMetricValue"] { font-size: 1.35rem !important; }
        [data-testid="stMetricLabel"] { font-size: 0.85rem !important; }
        .block-container { padding-top: 1.5rem !important; padding-bottom: 1.5rem !important; }
        .stTabs [aria-selected="true"] { color: #008163 !important; }
        .stTabs [data-baseweb="tab-highlight"] { background-color: #F47B20 !important; }
    </style>
""", unsafe_allow_html=True)

SEND_POLICY_POST = "All eligible (Apr-Sep)"
BACKTEST_TIERS = ["Persuadable", "Low ROI", "Sure Thing", "Lost Cause"]
STRATEGIES = ["Uplift targeting (recommended)", "Propensity targeting (same audience size)", "Send to all eligible"]


def money(x, signed=False):
    sign = "+" if signed and x > 0 else ("-" if x < 0 else "")
    return f"{sign}${abs(x):,.0f}"


def pct(x, signed=False):
    return f"{x:+.0%}" if signed else f"{x:.0%}"


def per_month(df, col):
    return df[col].sum() / df.month_end.nunique()


def strategy_frame(scores, strategy):
    persuadable = scores[scores.tier == "Persuadable"]
    if strategy == STRATEGIES[0]:
        return persuadable
    if strategy == STRATEGIES[1]:
        return scores.nlargest(len(persuadable), "p_with_offer")
    return scores


def strategy_summary(scores, strategy, discount):
    s = strategy_frame(scores, strategy)
    redemptions = s.p_with_offer.sum()
    return {
        "Strategy": strategy,
        "Audience": len(s),
        "Expected redemptions": redemptions,
        "Would buy anyway": s.p_without_offer.sum(),
        "Incremental purchases": s.uplift.sum(),
        "Discount cost": redemptions * discount,
        "Net incremental margin": s.expected_net_margin.sum(),
    }


portfolio = data.table("promo_portfolio")
monthly = data.table("promo_monthly")
promos = data.table("promotions").set_index("promotion_id")
monthly["month_end"] = pd.to_datetime(monthly.month_end)

REGIONS = sorted(monthly.region.unique().tolist())

with st.sidebar:
    region_pick = st.multiselect("Marketing region", REGIONS, default=REGIONS,
                                 help="Filters the spend, margin, and monthly results. Portfolio rankings and "
                                      "audiences are computed across all regions you can see.")
    st.divider()
    st.markdown("**Data source**")
    st.caption(data.source_label())
    st.caption(f"Signed in as {data.current_user()}")
    st.divider()
    st.caption("Demo date 2026-09-30. All members, stores, and numbers are synthetic.")

st.title(f"🏪 {BRAND} · Next Best Offer (NBO) Decision Engine")
st.markdown("Prioritizing promotions, targeting the shoppers an offer actually moves, and personalizing 1-to-1 offers.")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "1. Promotion Portfolio View",
    "2. Target Audience View",
    "3. Customer-Level View",
    "4. Measurement",
    "5. Ask Genie",
])

# ==========================================
# SCREEN 1: PROMOTION PORTFOLIO VIEW
# ==========================================
with tab1:
    st.header("📊 Promotion Portfolio View")
    st.caption("Since April every offer goes to everyone eligible. What is that buying? Every send keeps a 10% "
               "holdout, so incremental results are measured, not assumed.")

    if region_pick:
        monthly = monthly[monthly.region.isin(region_pick)]
    if len(region_pick) < len(REGIONS):
        st.caption(f"Region filter: {', '.join(region_pick) or 'none'}.")

    is_post = monthly.send_policy == SEND_POLICY_POST
    pre, post = monthly[~is_post], monthly[is_post]
    spend_pre, spend_post = per_month(pre, "discount_cost"), per_month(post, "discount_cost")
    inc_pre, inc_post = per_month(pre, "incremental_margin"), per_month(post, "incremental_margin")
    top = portfolio.iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Monthly discount spend, Apr–Sep", money(spend_post),
              f"{pct(spend_post / spend_pre - 1, True)} vs Jan–Mar", delta_color="inverse")
    c2.metric("Monthly incremental margin, Apr–Sep", money(inc_post),
              f"{money(inc_post - inc_pre, True)} vs Jan–Mar")
    c3.metric(f"{top.short_name} redemptions that would happen anyway",
              pct(top.redemptions_that_would_happen_anyway),
              f"{pct(top.redemption_rate_apr_sep)} redemption rate", delta_color="off")
    c4.metric("Annual margin gain from uplift targeting", money(portfolio.annual_gain_vs_blast.sum()),
              "vs sending to all eligible", delta_color="off")

    st.divider()

    st.subheader("Discount spend vs incremental margin, by month")
    trend = (monthly.groupby("month_end")[["discount_cost", "incremental_margin"]].sum().reset_index()
             .melt("month_end", var_name="measure", value_name="usd"))
    trend["measure"] = trend.measure.map({"discount_cost": "Discount spend",
                                          "incremental_margin": "Incremental margin (vs holdout)"})
    lines = alt.Chart(trend).mark_line(point=True).encode(
        x=alt.X("month_end:T", title=None, axis=alt.Axis(format="%b %Y")),
        y=alt.Y("usd:Q", title="USD"),
        color=alt.Color("measure:N", title=None,
                        scale=alt.Scale(range=[ORANGE, GREEN]), legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("month_end:T", format="%b %Y"), "measure", alt.Tooltip("usd:Q", format="$,.0f")],
    )
    # Between the last curated month and the first all-eligible month
    change_x = pre.month_end.max() + (post.month_end.min() - pre.month_end.max()) / 2
    rule = alt.Chart(pd.DataFrame({"x": [change_x]})).mark_rule(
        strokeDash=[4, 4], color="#888").encode(x="x:T")
    label = alt.Chart(pd.DataFrame({"x": [change_x],
                                    "t": ["Apr 1: send to all eligible"]})).mark_text(
        align="left", dx=4, dy=-110, color="#666").encode(x="x:T", text="t")
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#ccc").encode(y="y:Q")
    st.altair_chart((zero + lines + rule + label).properties(height=280), width="stretch")

    st.subheader("Promotion Opportunity Ranking")
    view = portfolio[["opportunity_rank", "promotion_name", "category", "eligible_members", "redemption_rate_apr_sep",
                      "measured_uplift_apr_sep", "blast_net_margin_per_send", "targeted_net_margin_per_send",
                      "annual_opportunity_targeted", "status"]].copy()
    view["redemption_rate_apr_sep"] *= 100
    view["measured_uplift_apr_sep"] *= 100
    st.dataframe(
        view,
        column_config={
            "opportunity_rank": st.column_config.NumberColumn("Rank", format="%d"),
            "promotion_name": "Promotion",
            "category": "Category",
            "eligible_members": st.column_config.NumberColumn("Eligible members", format="%d"),
            "redemption_rate_apr_sep": st.column_config.NumberColumn("Redemption rate", format="%.0f%%"),
            "measured_uplift_apr_sep": st.column_config.NumberColumn(
                "Measured lift", format="%.1f pts", help="Treatment conversion minus holdout conversion, Apr–Sep"),
            "blast_net_margin_per_send": st.column_config.NumberColumn("Net margin / send: all eligible",
                                                                       format="$%.0f"),
            "targeted_net_margin_per_send": st.column_config.NumberColumn("Net margin / send: targeted",
                                                                          format="$%.0f"),
            "annual_opportunity_targeted": st.column_config.NumberColumn("Annual opportunity", format="$%.0f"),
            "status": "Recommendation",
        },
        hide_index=True,
        width="stretch",
    )

    st.info(f"💡 **Executive Takeaway:** Redemption rate is the wrong scoreboard. **{top.short_name}** is the "
            f"biggest opportunity, but sent to everyone eligible it loses "
            f"{money(-top.blast_net_margin_per_send)} per send, because "
            f"{pct(top.redemptions_that_would_happen_anyway)} of redemptions come from shoppers who already buy "
            f"the pastry. Sent only to the shoppers it moves, it earns {money(top.targeted_net_margin_per_send)} "
            f"per send.")
    members = int(data.table("member_profile").shape[0]) if data.LOCAL else None
    st.caption("Pilot base of synthetic loyalty members. Dollar values scale linearly with the number of members "
               "reached." + (f" Members in this build: {members:,}." if members else ""))


# ==========================================
# SCREEN 2: TARGET AUDIENCE VIEW
# ==========================================
with tab2:
    st.header("🎯 Target Audience View")
    st.caption("Every eligible member is scored twice: likelihood to buy with the offer and without it. "
               "The difference is the lift the offer causes.")

    names = portfolio.set_index("promotion_name").promotion_id
    selected = st.selectbox("Select Promotion to Analyze:", names.index.tolist())
    pid = names[selected]
    promo = promos.loc[pid]
    scores = data.promotion_scores(pid)
    tiers = data.table("audience_tiers")
    tiers = tiers[tiers.promotion_id == pid].sort_values("tier_order")

    choice = st.radio("Campaign Targeting Strategy:", STRATEGIES, index=0, horizontal=True)
    summaries = {s: strategy_summary(scores, s, promo.discount_cost) for s in STRATEGIES}
    summ = summaries[choice]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Targeted audience", f"{summ['Audience']:,}", f"{summ['Audience'] / max(len(scores), 1):.0%} of eligible",
              delta_color="off")
    m2.metric("Expected redemptions", f"{summ['Expected redemptions']:,.0f}",
              f"{summ['Would buy anyway'] / max(summ['Expected redemptions'], 1):.0%} would buy anyway",
              delta_color="off")
    m3.metric("Discount cost per send", money(summ["Discount cost"]))
    m4.metric("Net incremental margin per send", money(summ["Net incremental margin"]),
              "pays back" if summ["Net incremental margin"] > 0 else "loses money",
              delta_color="normal" if summ["Net incremental margin"] > 0 else "inverse")

    st.divider()

    left, right = st.columns([1.25, 1])
    with left:
        st.subheader("Audience Uplift Breakdown")
        tv = tiers[["tier", "members", "avg_p_without_offer", "avg_p_with_offer", "avg_uplift",
                    "expected_net_margin", "action"]].copy()
        for col in ["avg_p_without_offer", "avg_p_with_offer", "avg_uplift"]:
            tv[col] *= 100
        st.dataframe(
            tv,
            column_config={
                "tier": "Tier",
                "members": st.column_config.NumberColumn("Members", format="%d"),
                "avg_p_without_offer": st.column_config.NumberColumn("Buys without offer", format="%.0f%%"),
                "avg_p_with_offer": st.column_config.NumberColumn("Buys with offer", format="%.0f%%"),
                "avg_uplift": st.column_config.NumberColumn("Lift", format="%.1f pts"),
                "expected_net_margin": st.column_config.NumberColumn("Net margin / send", format="$%.0f"),
                "action": "Action",
            },
            hide_index=True,
            width="stretch",
        )
    with right:
        st.subheader("Strategy comparison (one send)")
        comp = pd.DataFrame(summaries.values())
        comp["Strategy"] = comp.Strategy.str.replace(r" \(.*\)", "", regex=True)
        bars = alt.Chart(comp).mark_bar().encode(
            x=alt.X("Net incremental margin:Q", title="Net incremental margin per send (USD)"),
            y=alt.Y("Strategy:N", sort=None, title=None),
            color=alt.condition(alt.datum["Net incremental margin"] > 0, alt.value(GREEN), alt.value(RED)),
            tooltip=["Strategy", alt.Tooltip("Audience:Q", format=","),
                     alt.Tooltip("Discount cost:Q", format="$,.0f"),
                     alt.Tooltip("Net incremental margin:Q", format="$,.0f")],
        ).properties(height=160)
        st.altair_chart(bars, width="stretch")
        st.caption("Propensity targeting picks the same number of people as uplift targeting, ranked by "
                   "likelihood to buy. It fills the audience with shoppers who would buy anyway.")

    persuadable = tiers[tiers.tier == "Persuadable"]
    if len(persuadable) and summ["Net incremental margin"] > 0:
        st.success(f"💡 **Targeting Outcome:** Uplift targeting reaches {summ['Audience']:,} members and earns "
                   f"{money(summ['Net incremental margin'])} per send. Sending to all {len(scores):,} eligible "
                   f"members would earn {money(summaries[STRATEGIES[2]]['Net incremental margin'])}.")
    else:
        st.warning("💡 **Targeting Outcome:** No audience for this offer pays back at the current discount. "
                   "Redesign the incentive or retire it.")

    st.subheader("Approve campaign")
    a1, a2, a3 = st.columns([1.2, 1, 1])
    channel = a1.selectbox("Delivery channel", [promo.default_channel, "App push", "Email", "SMS"])
    a2.write("")
    a2.write("")
    if a2.button(f"Approve: {summ['Audience']:,} members", type="primary",
                 disabled=summ["Audience"] == 0):
        data.approve({
            "promotion_id": pid,
            "promotion_name": promo.promotion_name,
            "strategy": choice,
            "audience_size": int(summ["Audience"]),
            "expected_redemptions": float(round(summ["Expected redemptions"], 1)),
            "expected_discount_cost": float(round(summ["Discount cost"], 2)),
            "expected_net_margin": float(round(summ["Net incremental margin"], 2)),
            "channel": channel,
        })
        st.toast("Campaign approved and queued for activation")
    a3.caption("Approval writes the audience decision to `campaign_approvals` in Unity Catalog for the "
               "activation job to pick up.")
    hist = data.approvals()
    if not hist.empty:
        st.dataframe(hist, hide_index=True, width="stretch")


# ==========================================
# SCREEN 3: CUSTOMER-LEVEL VIEW
# ==========================================
with tab3:
    st.header("👤 Customer-Level View (1-to-1 Explainability)")
    st.caption("Inspect a shopper's behaviour, how every eligible promotion scores, and the offer that wins.")

    featured = data.table("featured_members")
    f1, f2 = st.columns([2, 1])
    pick = f1.selectbox("Select Individual Shopper Profile:", featured.display.tolist())
    typed = f2.text_input("…or look up a member ID", placeholder="e.g. 7110000042")
    member_id = int(featured.set_index("display").at[pick, "member_id"])
    if typed.strip():
        try:
            member_id = int(typed.strip().lstrip("#"))
        except ValueError:
            st.error("Member IDs are numbers.")
    prof, mscores = data.member(member_id)

    if prof is None:
        st.warning(f"No member {member_id}.")
    else:
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("CRM segment", prof.crm_segment)
        p2.metric("Visits per active week", f"{prof.visits_per_active_week:.1f}")
        p3.metric("Avg. basket", f"${prof.avg_basket_value:.2f}")
        p4.metric("Last visit", "Today" if prof.days_since_last_visit == 0 else f"{prof.days_since_last_visit} days ago")

        st.divider()
        left_c, right_c = st.columns([1, 1.25])

        with left_c:
            st.subheader("📡 Key Behavioral Signals")
            signals = [
                f"Member ID #{prof.member_id} · {prof.region} · home store {prof.home_store_id} · "
                f"{prof.tenure_months} months in the program",
                f"Coffee on {prof.coffee_rate:.0%} of visits; adds a pastry on {prof.pastry_with_coffee_rate:.0%} "
                f"of coffee visits",
                f"Visit mix: {prof.morning_share:.0%} morning, {prof.midday_share:.0%} midday, "
                f"{prof.afternoon_share:.0%} afternoon, {prof.late_night_share:.0%} late night",
                f"{prof.visits:,} visits in the last 12 months · "
                f"{'app user' if prof.app_user else 'no app'} · "
                f"{'opted in to offers' if prof.marketing_opt_in else 'not opted in'}",
            ]
            for sig in signals:
                st.markdown(f"- {sig}")

            st.subheader("🎯 Recommended Action")
            nbo = mscores[mscores.is_next_best_offer.astype(bool)]
            if len(nbo):
                row = nbo.iloc[0]
                pr = promos.loc[row.promotion_id]
                st.success(f"### {pr.promotion_name}\n**Delivery Channel:** {pr.default_channel}  \n"
                           f"**Expected net margin:** {money(row.expected_net_margin)} per send")
                st.info(f"**Why This Offer Won:** {row.reason}.")
            else:
                st.warning("### No offer\nNothing this shopper is eligible for changes what they buy enough to pay "
                           "for the discount. Holding back protects margin.")
                eligible = mscores[mscores.eligible.astype(bool)]
                if len(eligible):
                    st.info(f"**Why:** {eligible.sort_values('p_with_offer', ascending=False).iloc[0].reason}.")

        with right_c:
            st.subheader("⚖️ Promotion Scoring Breakdown")
            sv = mscores.merge(promos[["promotion_name"]], left_on="promotion_id", right_index=True)
            sv = sv.sort_values(["eligible", "expected_net_margin"], ascending=[False, False])
            sv["Decision"] = sv.apply(
                lambda r: "✅ Recommended NBO" if r.is_next_best_offer else
                ("Ineligible" if r.tier == "Ineligible" else f"Suppress ({r.tier})" if r.tier != "Persuadable"
                 else "Fallback"), axis=1)
            for col in ["p_without_offer", "p_with_offer", "uplift"]:
                sv[col] = (sv[col] * 100).where(sv.eligible.astype(bool))
            sv["expected_net_margin"] = sv.expected_net_margin.where(sv.eligible.astype(bool))
            st.dataframe(
                sv[["promotion_name", "p_with_offer", "p_without_offer", "uplift", "expected_net_margin", "Decision"]],
                column_config={
                    "promotion_name": "Promotion",
                    "p_with_offer": st.column_config.ProgressColumn(
                        "Buys with offer", format="%.0f%%", min_value=0, max_value=100),
                    "p_without_offer": st.column_config.NumberColumn("Buys without", format="%.0f%%"),
                    "uplift": st.column_config.NumberColumn("Lift", format="%.0f pts"),
                    "expected_net_margin": st.column_config.NumberColumn("Net margin", format="$%.2f"),
                },
                hide_index=True,
                width="stretch",
            )
            st.caption("All eligible promotions are scored at once. Only the offer with the highest positive net "
                       "margin is served, so shoppers aren't flooded and sure things aren't discounted.")


# ==========================================
# SCREEN 4: MEASUREMENT
# ==========================================
with tab4:
    st.header("🧪 Measurement")
    st.caption("Every send holds back 10% of the audience. Comparing the two groups shows what each offer "
               "really caused, and whether the model's tiers hold up.")

    bt = data.table("tier_backtest")
    bt = bt.merge(promos[["short_name"]], left_on="promotion_id", right_index=True)
    bt = bt[bt.holdout_sends >= 30]
    st.subheader("Measured lift by model tier, Apr–Sep sends")
    chart = alt.Chart(bt).mark_bar().encode(
        x=alt.X("tier:N", title=None, sort=BACKTEST_TIERS),
        y=alt.Y("measured_uplift:Q", title="Treatment minus holdout conversion", axis=alt.Axis(format="%")),
        color=alt.Color("tier:N", legend=None,
                        scale=alt.Scale(domain=BACKTEST_TIERS,
                                        range=[GREEN, "#9AA5A8", ORANGE, RED])),
        column=alt.Column("short_name:N", title=None),
        tooltip=["short_name", "tier", alt.Tooltip("measured_uplift:Q", format=".1%"),
                 alt.Tooltip("treatment_sends:Q", format=","), alt.Tooltip("holdout_sends:Q", format=",")],
    ).properties(width=150, height=220)
    st.altair_chart(chart)
    st.caption("Persuadables show a large measured lift; sure things show almost none. This is the evidence for "
               "suppressing them.")

    st.subheader("Monthly results by promotion")
    mt = monthly.groupby(["month_end", "short_name"], as_index=False)[
        ["sends", "holdout", "redemptions", "holdout_conversions", "discount_cost", "incremental_margin"]].sum()
    mt["redemption_rate"] = mt.redemptions / mt.sends * 100
    mt["measured_lift"] = (mt.redemptions / mt.sends - mt.holdout_conversions / mt.holdout) * 100
    mt = mt.sort_values(["month_end", "short_name"], ascending=[False, True])
    mt["month_end"] = mt.month_end.dt.strftime("%b %Y")
    st.dataframe(
        mt[["month_end", "short_name", "sends", "holdout", "redemption_rate", "measured_lift", "discount_cost",
            "incremental_margin"]],
        column_config={
            "month_end": "Month",
            "short_name": "Promotion",
            "sends": st.column_config.NumberColumn("Sends", format="%d"),
            "holdout": st.column_config.NumberColumn("Holdout", format="%d"),
            "redemption_rate": st.column_config.NumberColumn("Redemption rate", format="%.0f%%"),
            "measured_lift": st.column_config.NumberColumn("Measured lift", format="%.1f pts"),
            "discount_cost": st.column_config.NumberColumn("Discount spend", format="$%.0f"),
            "incremental_margin": st.column_config.NumberColumn("Incremental margin", format="$%.0f"),
        },
        hide_index=True,
        width="stretch",
        height=320,
    )


# ==========================================
# SCREEN 5: ASK GENIE
# ==========================================
with tab5:
    st.header("💬 Ask Genie")
    st.caption("Plain-English questions over the same governed metric view and gold tables the dashboard reads.")

    if not data.genie_enabled():
        st.info("Genie isn't connected to this app yet. Set `GENIE_SPACE_ID` (see DEPLOY.md) to turn this on. "
                "On a local preview, ask in the Genie space in the workspace instead.")
    else:
        examples = [
            "Why did discount spend go up after April but incremental margin go down?",
            "Which promotion has the biggest gap between redemption rate and real lift?",
            "What would targeting only persuadable shoppers be worth?",
        ]
        q_pick = st.selectbox("Example questions", ["Type your own…", *examples])
        question = st.text_input("Question", value="" if q_pick == "Type your own…" else q_pick)
        if st.button("Ask", type="primary", disabled=not question.strip()):
            with st.spinner("Genie is working…"):
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
