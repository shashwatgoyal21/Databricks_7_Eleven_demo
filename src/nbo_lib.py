"""Simulation, features, uplift model, and gold tables for the Next Best Offer demo.

Pure numpy / pandas / scikit-learn, so the same code runs in the Databricks notebooks and locally
(see local_run.py). All members, stores, and numbers are fictional.

The story is built into the simulation. On 2026-04-01 the loyalty team moved from small curated
sends to sending every offer to everyone eligible. Discount spend jumped, but incremental margin
did not, because most of the new recipients were "sure things": shoppers who already buy the
promoted item. The clearest case is the Morning Coffee + Croissant bundle: about 40% of morning
commuters already add a pastry to most coffee visits. They redeem the most and are moved the least.
Every promotion keeps a 10% holdout, so the true uplift is measurable from the data.
"""

import numpy as np
import pandas as pd

DEMO_DATE = pd.Timestamp("2026-09-30")
HISTORY_START = pd.Timestamp("2025-10-01")
HISTORY_DAYS = (DEMO_DATE - HISTORY_START).days + 1
PRE_END = pd.Timestamp("2026-03-31")
POLICY_CHANGE = pd.Timestamp("2026-04-01")
SEND_POLICY_PRE, SEND_POLICY_POST = "Curated sends (Jan-Mar)", "All eligible (Apr-Sep)"
HERO_PROMOTION = "PR01"  # the promotion the demo story is told through
WAVE_MONTHS = pd.period_range("2026-01", "2026-09", freq="M")
WAVE_DAY = 5
HOLDOUT = 0.10
CURATED_PICK = (0.45, 0.06)  # send rate before April: offer pays back / does not
LAPSE_SHARE = 0.15
LAPSED_AFTER_DAYS = 14
WINBACK_WINDOW_DAYS = 90

REGIONS = {"Texas": 0.32, "California": 0.26, "Florida": 0.22, "Northeast": 0.20}
STORES_PER_REGION = {"Texas": 38, "California": 31, "Florida": 27, "Northeast": 24}
CITIES = {
    "Texas": ["Dallas", "Fort Worth", "Houston", "Austin", "San Antonio"],
    "California": ["Los Angeles", "San Diego", "San Jose", "Sacramento"],
    "Florida": ["Miami", "Tampa", "Orlando", "Jacksonville"],
    "Northeast": ["New York", "Boston", "Philadelphia", "Newark"],
}

DAYPARTS = ["Morning", "Midday", "Afternoon", "Evening", "Late Night"]
DAYPART_START_HOUR = [5, 10, 14, 18, 22]
DAYPART_HOURS = [5, 4, 4, 4, 7]

CATEGORIES = ["coffee", "pastry", "roller_grill", "sandwich", "energy_drink",
              "cold_dispensed", "snacks", "packaged_beverage"]
PRICES = np.array([2.49, 2.29, 1.99, 5.49, 3.29, 1.89, 2.19, 2.39])

SEGMENTS = {
    "Morning Commuter": dict(share=0.30, visits=4.0, daypart=[0.78, 0.10, 0.06, 0.04, 0.02],
                             cat=[0.85, 0.0, 0.05, 0.08, 0.06, 0.03, 0.15, 0.12]),
    "Afternoon Snacker": dict(share=0.22, visits=2.5, daypart=[0.05, 0.12, 0.68, 0.12, 0.03],
                              cat=[0.10, 0.05, 0.38, 0.06, 0.10, 0.30, 0.55, 0.35]),
    "Lunch Regular": dict(share=0.18, visits=3.0, daypart=[0.08, 0.70, 0.12, 0.08, 0.02],
                          cat=[0.15, 0.04, 0.12, 0.55, 0.05, 0.10, 0.30, 0.45]),
    "Late-Night Regular": dict(share=0.10, visits=2.0, daypart=[0.03, 0.05, 0.10, 0.22, 0.60],
                               cat=[0.05, 0.03, 0.30, 0.08, 0.55, 0.12, 0.45, 0.25]),
    "Occasional": dict(share=0.20, visits=0.7, daypart=[0.22, 0.25, 0.25, 0.18, 0.10],
                       cat=[0.25, 0.08, 0.12, 0.15, 0.10, 0.15, 0.35, 0.35]),
}
SEGMENT_NAMES = list(SEGMENTS)
PASTRY_REGULAR_SHARE = 0.40   # of morning commuters
PASTRY_ATTACH = {True: 0.55, False: 0.05}

PROMOTIONS = pd.DataFrame([
    {"promotion_id": "PR01", "promotion_name": "Morning Coffee + Croissant Bundle ($1.50 Off)",
     "short_name": "Coffee + Croissant", "category": "Fresh Bakery & Hot Beverages",
     "objective": "Basket expansion & bakery waste reduction", "discount_cost": 1.50, "unit_margin": 3.20,
     "default_channel": "POS pin-pad + app banner",
     "eligibility_rule": "Buys coffee on 35%+ of visits, 40%+ of visits in the morning, active in the last 14 days"},
    {"promotion_id": "PR02", "promotion_name": "Free Slurpee Win-Back (14+ Days Inactive)",
     "short_name": "Slurpee Win-Back", "category": "Cold Dispensed",
     "objective": "Churn prevention", "discount_cost": 1.10, "unit_margin": 3.40,
     "default_channel": "Push + SMS",
     "eligibility_rule": "No visit in 14 to 90 days"},
    {"promotion_id": "PR03", "promotion_name": "BOGO 50% Off Roller Grill Taquitos",
     "short_name": "Taquito BOGO", "category": "Hot Foods",
     "objective": "Afternoon traffic builder", "discount_cost": 0.75, "unit_margin": 2.80,
     "default_channel": "Geofenced app push",
     "eligibility_rule": "30%+ of visits in the afternoon, active in the last 14 days"},
    {"promotion_id": "PR04", "promotion_name": "2x Loyalty Points on Fresh Sandwiches",
     "short_name": "2x Sandwich Points", "category": "Fresh Food",
     "objective": "Margin mix shift", "discount_cost": 0.80, "unit_margin": 2.30,
     "default_channel": "App deals tab + email",
     "eligibility_rule": "30%+ of visits at midday, active in the last 14 days"},
    {"promotion_id": "PR05", "promotion_name": "$1 Off Energy Drinks (Late Night)",
     "short_name": "Late-Night Energy $1 Off", "category": "Packaged Beverages",
     "objective": "Late-night basket add-on", "discount_cost": 1.00, "unit_margin": 1.40,
     "default_channel": "App push (after 9 PM)",
     "eligibility_rule": "25%+ of visits late at night, active in the last 14 days"},
])

FIRST = ["Alex", "Maria", "James", "Priya", "Marcus", "Sofia", "Daniel", "Aisha", "Kevin", "Lucia",
         "Ryan", "Mei", "Carlos", "Hannah", "Tyler", "Fatima", "Jordan", "Elena", "Brandon", "Grace",
         "Diego", "Olivia", "Andre", "Nina", "Ethan", "Camila", "Jamal", "Hailey", "Victor", "Zoe"]
LAST = ["Rivera", "Nguyen", "Smith", "Patel", "Johnson", "Garcia", "Kim", "Williams", "Lopez", "Brown",
        "Chen", "Davis", "Martinez", "Wilson", "Hernandez", "Moore", "Taylor", "Thomas", "Clark", "Lewis",
        "Walker", "Young", "Allen", "Scott", "Green", "Baker", "Adams", "Nelson", "Hill", "Campbell"]

MODEL_FEATURES = [
    "visits_per_active_week", "morning_share", "midday_share", "afternoon_share", "evening_share",
    "late_night_share", "coffee_rate", "pastry_rate", "pastry_with_coffee_rate", "roller_grill_rate",
    "sandwich_rate", "energy_drink_rate", "cold_dispensed_rate", "avg_basket_value",
    "tenure_months", "app_user",
]

# Decision thresholds applied to model scores
MIN_UPLIFT = 0.04
MIN_NET_MARGIN = 0.05
SURE_THING_BASELINE = 0.35
LOST_CAUSE_RESPONSE = 0.10

TIER_ORDER = ["Persuadable", "Sure Thing", "Lost Cause", "Low ROI"]
TIER_ACTION = {
    "Persuadable": "Target: offer changes behaviour and pays back",
    "Sure Thing": "Suppress: buys anyway, discount is pure cost",
    "Lost Cause": "Suppress: unlikely to respond either way",
    "Low ROI": "Hold: small lift does not cover the discount",
}


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def simulate(members=25_000, seed=711):
    """Return the raw tables as pandas DataFrames: stores, loyalty_members, pos_baskets,
    promotions, offer_history."""
    rng = np.random.default_rng(seed)

    # Stores
    store_rows, store_id = [], 1001
    for region, n in STORES_PER_REGION.items():
        for _ in range(n):
            store_rows.append({"store_id": store_id, "region": region,
                               "city": str(rng.choice(CITIES[region])),
                               "has_fresh_bakery": bool(rng.random() < 0.8)})
            store_id += 1
    stores = pd.DataFrame(store_rows)
    stores_by_region = {r: stores.loc[stores.region == r, "store_id"].to_numpy() for r in REGIONS}

    # Members and their hidden traits
    n = members
    seg_idx = rng.choice(len(SEGMENT_NAMES), size=n, p=[SEGMENTS[s]["share"] for s in SEGMENT_NAMES])
    region = rng.choice(list(REGIONS), size=n, p=list(REGIONS.values()))
    home_store = np.array([rng.choice(stores_by_region[r]) for r in region])
    lam = np.array([SEGMENTS[SEGMENT_NAMES[s]]["visits"] for s in seg_idx]) * rng.lognormal(0, 0.3, n)
    commuter = seg_idx == SEGMENT_NAMES.index("Morning Commuter")
    pastry_regular = commuter & (rng.random(n) < PASTRY_REGULAR_SHARE)
    lapses = rng.random(n) < LAPSE_SHARE
    lapse_day = np.where(lapses, rng.integers(60, HISTORY_DAYS - 14, n), HISTORY_DAYS + 1)
    tenure = rng.integers(3, 96, n)
    app_user = rng.random(n) < 0.70
    opt_in = rng.random(n) < 0.78
    response_effect = rng.lognormal(0, 0.25, n)

    member_id = 7_110_000_001 + np.arange(n)
    first = rng.choice(FIRST, n)
    last = rng.choice(LAST, n)
    loyalty_members = pd.DataFrame({
        "member_id": member_id,
        "first_name": first,
        "last_name": last,
        "email": [f"{f.lower()}.{l.lower()}{i % 1000}@example.com" for f, l, i in zip(first, last, range(n))],
        "region": region,
        "home_store_id": home_store,
        "crm_segment": np.array(SEGMENT_NAMES)[seg_idx],
        "tenure_months": tenure,
        "app_user": app_user,
        "marketing_opt_in": opt_in,
        "enrolled_date": (DEMO_DATE - pd.to_timedelta(tenure * 30, unit="D")).normalize(),
    })

    # Baskets
    counts = rng.poisson(lam * HISTORY_DAYS / 7)
    m = np.repeat(np.arange(n), counts)
    day = rng.integers(0, HISTORY_DAYS, m.size)
    keep = day < lapse_day[m]
    m, day = m[keep], day[keep]
    v = m.size

    dp_cum = np.cumsum(np.array([SEGMENTS[s]["daypart"] for s in SEGMENT_NAMES]), axis=1)
    dp = (rng.random(v)[:, None] > dp_cum[seg_idx[m]]).sum(axis=1).clip(0, 4)
    hour = np.array(DAYPART_START_HOUR)[dp] + (rng.random(v) * np.array(DAYPART_HOURS)[dp]).astype(int)
    minute = rng.integers(0, 60, v)

    cat_p = np.array([SEGMENTS[s]["cat"] for s in SEGMENT_NAMES])[seg_idx[m]]
    morning = dp == 0
    cat_p[:, 0] = np.where(morning, cat_p[:, 0], cat_p[:, 0] * 0.5)
    flags = rng.random((v, len(CATEGORIES))) < cat_p
    attach = np.where(pastry_regular[m], PASTRY_ATTACH[True], PASTRY_ATTACH[False])
    commuter_visit = commuter[m]
    flags[:, 1] = np.where(commuter_visit, flags[:, 0] & (rng.random(v) < attach), flags[:, 1])
    empty = ~flags.any(axis=1)
    flags[empty, 6] = True

    away = rng.random(v) < 0.15
    region_codes = pd.Categorical(region, categories=list(REGIONS)).codes
    store_choice = np.empty(v, dtype=np.int64)
    store_choice[~away] = home_store[m[~away]]
    for code, r in enumerate(REGIONS):
        idx = np.where(away & (region_codes[m] == code))[0]
        store_choice[idx] = rng.choice(stores_by_region[r], idx.size)

    extra_items = rng.poisson(0.3, v)
    basket_value = (flags * PRICES).sum(axis=1) + extra_items * rng.uniform(1.0, 3.5, v)
    order = np.lexsort((minute, hour, day))
    ts = HISTORY_START + pd.to_timedelta(day * 1440 + hour * 60 + minute, unit="m")
    pos_baskets = pd.DataFrame({
        "basket_id": np.arange(1, v + 1, dtype=np.int64),
        "member_id": member_id[m][order],
        "store_id": store_choice[order],
        "basket_ts": ts[order],
        "daypart": np.array(DAYPARTS)[dp][order],
        "items": (flags.sum(axis=1) + extra_items)[order].astype(np.int16),
        "basket_value": np.round(basket_value, 2)[order],
        **{f"has_{c}": flags[order, i] for i, c in enumerate(CATEGORIES)},
    })

    # Offer waves: one send per promotion per month, 10% holdout in every wave
    late_night = seg_idx == SEGMENT_NAMES.index("Late-Night Regular")
    snacker = seg_idx == SEGMENT_NAMES.index("Afternoon Snacker")
    lunch = seg_idx == SEGMENT_NAMES.index("Lunch Regular")
    other = rng.random((n, 5))
    trait_eligible = {
        "PR01": commuter | (~commuter & (other[:, 0] < 0.15)),
        "PR03": snacker | (~snacker & (other[:, 2] < 0.25)),
        "PR04": lunch | (~lunch & (other[:, 3] < 0.30)),
        "PR05": late_night | (~late_night & (other[:, 4] < 0.20)),
    }

    def truth(pid, idx, wave_day):
        """True baseline (no offer) and uplift for members idx."""
        if pid == "PR01":
            base = np.where(pastry_regular[idx], 0.62, np.where(commuter[idx], 0.08, 0.12))
            upl = np.where(pastry_regular[idx], 0.03, np.where(commuter[idx], 0.22, 0.06))
        elif pid == "PR02":
            high, mid = lam[idx] >= 3.0, lam[idx] >= 1.2
            base = np.where(high, 0.18, np.where(mid, 0.08, 0.02))
            upl = np.where(high, 0.30, np.where(mid, 0.15, 0.02))
            decay = 1 - 0.5 * (wave_day - lapse_day[idx]) / WINBACK_WINDOW_DAYS
            upl = upl * decay
        elif pid == "PR03":
            base = np.where(snacker[idx], 0.28, 0.06)
            upl = np.where(snacker[idx], 0.16, 0.05)
        elif pid == "PR04":
            base = np.where(lunch[idx], 0.50, 0.10)
            upl = np.where(lunch[idx], 0.05, 0.09)
        else:
            base = np.where(late_night[idx], 0.55, 0.07)
            upl = np.where(late_night[idx], 0.02, 0.05)
        base = np.clip(base * response_effect[idx], 0.0, 0.92)
        return base, upl

    offers, event_id = [], 1
    promo = PROMOTIONS.set_index("promotion_id")
    for p in WAVE_MONTHS:
        sent = pd.Timestamp(year=p.year, month=p.month, day=WAVE_DAY)
        wave_day = (sent - HISTORY_START).days
        active = lapse_day > wave_day
        for pid in PROMOTIONS.promotion_id:
            if pid == "PR02":
                since = wave_day - lapse_day
                eligible = (since >= LAPSED_AFTER_DAYS) & (since <= WINBACK_WINDOW_DAYS)
            else:
                eligible = trait_eligible[pid] & active
            idx = np.where(eligible & opt_in)[0]
            base, upl = truth(pid, idx, wave_day)
            if sent < POLICY_CHANGE:
                # Curated sends: marketers hand-pick segments, so the members picked lean towards
                # the ones the offer actually moves
                pays = upl * promo.at[pid, "unit_margin"] > (base + upl) * promo.at[pid, "discount_cost"]
                pick = rng.random(idx.size) < np.where(pays, CURATED_PICK[0], CURATED_PICK[1])
                idx, base, upl = idx[pick], base[pick], upl[pick]
            control = rng.random(idx.size) < HOLDOUT
            p_buy = np.clip(np.where(control, base, base + upl), 0, 0.97)
            converted = rng.random(idx.size) < p_buy
            channel = np.where(app_user[idx], "App push", "Email")
            discount = np.where(~control & converted, promo.at[pid, "discount_cost"], 0.0)
            offers.append(pd.DataFrame({
                "offer_event_id": np.arange(event_id, event_id + idx.size, dtype=np.int64),
                "member_id": member_id[idx],
                "region": region[idx],
                "promotion_id": pid,
                "sent_date": sent,
                "channel": channel,
                "group": np.where(control, "Holdout", "Treatment"),
                "converted": converted,
                "redeemed": converted & ~control,
                "discount_cost": discount,
            }))
            event_id += idx.size
    offer_history = pd.concat(offers, ignore_index=True)

    return {
        "stores": stores,
        "loyalty_members": loyalty_members,
        "pos_baskets": pos_baskets,
        "promotions": PROMOTIONS.copy(),
        "offer_history": offer_history,
    }


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

def member_features(pos_baskets, loyalty_members, start, end):
    """One row per member: behaviour rates over [start, end] plus CRM attributes."""
    ts = pos_baskets.basket_ts
    b = pos_baskets[(ts >= start) & (ts < end + pd.Timedelta(days=1))]
    share_cols = ["morning_share", "midday_share", "afternoon_share", "evening_share", "late_night_share"]
    rate_cols = [f"{c}_rate" for c in CATEGORIES]
    # One frame of per-basket indicators, so a single groupby computes every member rate
    x = pd.DataFrame({
        "member_id": b.member_id,
        "week": (b.basket_ts - start).dt.days // 7,
        "basket_ts": b.basket_ts,
        "basket_value": b.basket_value,
        **{col: b.daypart == part for part, col in zip(DAYPARTS, share_cols)},
        **{f"{c}_rate": b[f"has_{c}"] for c in CATEGORIES},
        "coffee_and_pastry": b.has_coffee & b.has_pastry,
    })
    g = x.groupby("member_id")
    f = g.agg(visits=("week", "size"), active_weeks=("week", "nunique"), last_visit=("basket_ts", "max"),
              avg_basket_value=("basket_value", "mean"))
    f[share_cols + rate_cols] = g[share_cols + rate_cols].mean()
    both = g.coffee_and_pastry.sum()
    coffee = g.coffee_rate.sum()
    f["pastry_with_coffee_rate"] = (both / coffee.replace(0, np.nan)).fillna(0.0)
    f["visits_per_active_week"] = f.visits / f.active_weeks

    out = loyalty_members[["member_id", "region", "home_store_id", "crm_segment", "tenure_months",
                           "app_user", "marketing_opt_in"]].merge(f.reset_index(), on="member_id", how="left")
    out["visits"] = out.visits.fillna(0).astype(int)
    out["active_weeks"] = out.active_weeks.fillna(0).astype(int)
    out["days_since_last_visit"] = (end - out.last_visit.dt.normalize()).dt.days
    out["days_since_last_visit"] = out.days_since_last_visit.fillna((end - start).days + 1).astype(int)
    rate_cols = [c for c in out.columns if c.endswith("_share") or c.endswith("_rate")]
    out[rate_cols] = out[rate_cols].fillna(0.0)
    out[["avg_basket_value", "visits_per_active_week"]] = out[["avg_basket_value", "visits_per_active_week"]].fillna(0.0)
    out["app_user"] = out.app_user.astype(int)
    return out.drop(columns=["last_visit"])


def eligibility(features):
    """Eligibility of each member for each promotion, from observed behaviour as of the window end."""
    f = features
    active = f.days_since_last_visit < LAPSED_AFTER_DAYS
    opt = f.marketing_opt_in.astype(bool)
    return pd.DataFrame({
        "PR01": active & (f.coffee_rate >= 0.35) & (f.morning_share >= 0.40),
        "PR02": f.days_since_last_visit.between(LAPSED_AFTER_DAYS, WINBACK_WINDOW_DAYS) & (f.visits > 0),
        "PR03": active & (f.afternoon_share >= 0.30),
        "PR04": active & (f.midday_share >= 0.30),
        "PR05": active & (f.late_night_share >= 0.25),
    }).mul(opt, axis=0).set_index(f.member_id)


# ---------------------------------------------------------------------------
# Uplift model (two-model / T-learner per promotion)
# ---------------------------------------------------------------------------

def _classifier(min_leaf):
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(max_iter=120, max_depth=3, learning_rate=0.08,
                                          min_samples_leaf=min_leaf, random_state=0)


def train_uplift(offer_history, train_features):
    """Fit one response model on treatment and one on holdout per promotion.
    Returns {promotion_id: {"treated": model, "control": model, "treated_rows": int, "control_rows": int}}."""
    data = offer_history.merge(train_features[["member_id"] + MODEL_FEATURES], on="member_id", how="inner")
    models = {}
    for pid, d in data.groupby("promotion_id"):
        t, c = d[d.group == "Treatment"], d[d.group == "Holdout"]
        models[pid] = {
            "treated": _classifier(40).fit(t[MODEL_FEATURES], t.converted),
            "control": _classifier(60).fit(c[MODEL_FEATURES], c.converted),
            "treated_rows": len(t),
            "control_rows": len(c),
        }
    return models


def predict_response(mdl, X):
    """Likelihood to buy with and without the offer, from one promotion's pair of models."""
    return mdl["treated"].predict_proba(X)[:, 1], mdl["control"].predict_proba(X)[:, 1]


def score_members(models, features):
    """Score every member against every promotion and pick the next best offer."""
    elig = eligibility(features)
    promo = PROMOTIONS.set_index("promotion_id")
    X = features[MODEL_FEATURES]
    frames = []
    for pid, mdl in models.items():
        p_t, p_c = predict_response(mdl, X)
        uplift = np.clip(p_t - p_c, -0.2, 0.6)
        net = uplift * promo.at[pid, "unit_margin"] - p_t * promo.at[pid, "discount_cost"]
        frames.append(pd.DataFrame({
            "member_id": features.member_id.to_numpy(),
            "region": features.region.to_numpy(),
            "promotion_id": pid,
            "eligible": elig[pid].to_numpy(),
            "p_without_offer": p_c,
            "p_with_offer": p_t,
            "uplift": uplift,
            "expected_net_margin": net,
        }))
    s = pd.concat(frames, ignore_index=True)

    tier = np.select(
        [(s.expected_net_margin > MIN_NET_MARGIN) & (s.uplift >= MIN_UPLIFT),
         (s.p_without_offer >= SURE_THING_BASELINE) & (s.uplift < MIN_UPLIFT + 0.02),
         s.p_with_offer < LOST_CAUSE_RESPONSE],
        ["Persuadable", "Sure Thing", "Lost Cause"], default="Low ROI")
    s["tier"] = np.where(s.eligible, tier, "Ineligible")

    rank_key = np.where(s.tier == "Persuadable", s.expected_net_margin, -np.inf)
    s["rank"] = (pd.Series(rank_key).groupby(s.member_id).rank(ascending=False, method="first")
                 .astype(int).to_numpy())
    s["is_next_best_offer"] = (s["rank"] == 1) & (s.tier == "Persuadable")
    s["reason"] = _reasons(s, features)
    return s


def _pct(x):
    return f"{x:.0%}"


def _reasons(s, features):
    reasons = pd.Series("Does not meet the eligibility rule", index=s.index, dtype=object)
    el = s[s.tier != "Ineligible"]
    f = features.set_index("member_id").loc[el.member_id]
    r = []
    for row, fr in zip(el.itertuples(index=False), f.itertuples(index=False)):
        pid, tier = row.promotion_id, row.tier
        lift = f"{row.uplift * 100:+.0f} pts lift"
        if pid == "PR01":
            sig = (f"Coffee on {_pct(fr.coffee_rate)} of visits; adds a pastry on "
                   f"{_pct(fr.pastry_with_coffee_rate)} of coffee visits")
        elif pid == "PR02":
            sig = (f"No visit in {fr.days_since_last_visit} days; used to visit "
                   f"{fr.visits_per_active_week:.1f}x a week")
        elif pid == "PR03":
            sig = (f"{_pct(fr.afternoon_share)} of visits in the afternoon; roller grill on "
                   f"{_pct(fr.roller_grill_rate)} of visits")
        elif pid == "PR04":
            sig = f"{_pct(fr.midday_share)} of visits at midday; sandwich on {_pct(fr.sandwich_rate)} of visits"
        else:
            sig = (f"{_pct(fr.late_night_share)} of visits late at night; energy drink on "
                   f"{_pct(fr.energy_drink_rate)} of visits")
        if tier == "Sure Thing":
            r.append(f"{sig}. Would likely buy without the offer ({_pct(row.p_without_offer)}), so the discount is mostly cost")
        elif tier == "Persuadable":
            r.append(f"{sig}. Offer moves purchase likelihood from {_pct(row.p_without_offer)} to "
                     f"{_pct(row.p_with_offer)} ({lift})")
        elif tier == "Lost Cause":
            r.append(f"{sig}. Unlikely to respond either way ({_pct(row.p_with_offer)} with the offer)")
        else:
            r.append(f"{sig}. {lift} does not cover the discount")
    reasons[el.index] = r
    return reasons


# ---------------------------------------------------------------------------
# Gold tables
# ---------------------------------------------------------------------------

def build_gold(raw, scores, features):
    promo = raw["promotions"].set_index("promotion_id")
    oh = raw["offer_history"].copy()
    oh["month_end"] = oh.sent_date + pd.offsets.MonthEnd(0)
    treated = oh.group == "Treatment"

    # promo_monthly: month x promotion x region, sums only
    g = oh.assign(
        sends=treated.astype(int), holdout=(~treated).astype(int),
        conv_t=(oh.converted & treated).astype(int), conv_c=(oh.converted & ~treated).astype(int),
    ).groupby(["month_end", "promotion_id", "region"], as_index=False)[
        ["sends", "holdout", "conv_t", "conv_c", "discount_cost"]].sum()
    # Expected conversions without the offer, from the holdout rate at month x promotion grain
    h = g.groupby(["month_end", "promotion_id"])[["conv_c", "holdout"]].transform("sum")
    g["expected_baseline_conversions"] = g.sends * (h.conv_c / h.holdout.clip(lower=1))
    g["incremental_conversions"] = g.conv_t - g.expected_baseline_conversions
    g["incremental_margin"] = (g.incremental_conversions * g.promotion_id.map(promo.unit_margin)
                               - g.discount_cost)
    promo_monthly = g.rename(columns={"conv_t": "redemptions", "conv_c": "holdout_conversions"})
    promo_monthly = promo_monthly.merge(raw["promotions"][["promotion_id", "promotion_name", "short_name"]],
                                        on="promotion_id")
    promo_monthly["send_policy"] = np.where(promo_monthly.month_end < POLICY_CHANGE,
                                            SEND_POLICY_PRE, SEND_POLICY_POST)

    # audience_tiers: promotion x tier, one monthly send
    el = scores[scores.eligible]
    tiers = el.groupby(["promotion_id", "tier"], as_index=False).agg(
        members=("member_id", "count"),
        avg_p_without_offer=("p_without_offer", "mean"),
        avg_p_with_offer=("p_with_offer", "mean"),
        avg_uplift=("uplift", "mean"),
        expected_redemptions=("p_with_offer", "sum"),
        expected_incremental_conversions=("uplift", "sum"),
        expected_net_margin=("expected_net_margin", "sum"),
    )
    tiers["expected_discount_cost"] = tiers.expected_redemptions * tiers.promotion_id.map(promo.discount_cost)
    tiers["action"] = tiers.tier.map(TIER_ACTION)
    tiers["tier_order"] = tiers.tier.map({t: i for i, t in enumerate(TIER_ORDER)})
    tiers = tiers.sort_values(["promotion_id", "tier_order"]).reset_index(drop=True)

    # tier_backtest: measured lift by predicted tier on the Apr-Sep sends
    post = oh[oh.sent_date >= POLICY_CHANGE].merge(
        scores[["member_id", "promotion_id", "tier"]], on=["member_id", "promotion_id"])
    post = post[post.tier != "Ineligible"]
    bt = post.groupby(["promotion_id", "tier", "group"]).converted.agg(["sum", "count"]).unstack("group")
    backtest = pd.DataFrame({
        "treatment_sends": bt[("count", "Treatment")],
        "holdout_sends": bt[("count", "Holdout")],
        "treatment_conversion_rate": bt[("sum", "Treatment")] / bt[("count", "Treatment")],
        "holdout_conversion_rate": bt[("sum", "Holdout")] / bt[("count", "Holdout")],
    }).reset_index()
    backtest["measured_uplift"] = backtest.treatment_conversion_rate - backtest.holdout_conversion_rate

    # promo_portfolio: one row per promotion
    rows = []
    post_m = promo_monthly[promo_monthly.send_policy == SEND_POLICY_POST]
    months = post_m.month_end.nunique()
    for pid, p in promo.iterrows():
        e = el[el.promotion_id == pid]
        tgt = e[e.tier == "Persuadable"]
        pm = post_m[post_m.promotion_id == pid]
        redemption_rate = pm.redemptions.sum() / max(pm.sends.sum(), 1)
        holdout_rate = pm.holdout_conversions.sum() / max(pm.holdout.sum(), 1)
        blast_net = e.expected_net_margin.sum()
        tgt_net = tgt.expected_net_margin.sum()
        rows.append({
            "promotion_id": pid,
            "promotion_name": p.promotion_name,
            "short_name": p.short_name,
            "category": p.category,
            "objective": p.objective,
            "eligible_members": len(e),
            "persuadable_members": len(tgt),
            "sure_thing_members": int((e.tier == "Sure Thing").sum()),
            "redemption_rate_apr_sep": redemption_rate,
            "measured_uplift_apr_sep": redemption_rate - holdout_rate,
            "discount_spend_per_month_apr_sep": pm.discount_cost.sum() / months,
            "incremental_margin_per_month_apr_sep": pm.incremental_margin.sum() / months,
            "blast_discount_cost_per_send": e.p_with_offer.sum() * p.discount_cost,
            "blast_net_margin_per_send": blast_net,
            "targeted_discount_cost_per_send": tgt.p_with_offer.sum() * p.discount_cost,
            "targeted_net_margin_per_send": tgt_net,
            # The share of redemptions that would have happened without the offer
            "redemptions_that_would_happen_anyway": holdout_rate / max(redemption_rate, 1e-9),
            "annual_opportunity_targeted": tgt_net * 12,
            "annual_gain_vs_blast": (tgt_net - blast_net) * 12,
        })
    portfolio = pd.DataFrame(rows)
    portfolio["status"] = np.select(
        [portfolio.targeted_net_margin_per_send <= 0,
         portfolio.blast_net_margin_per_send < 0],
        ["Retire or redesign", "Fix targeting"], default="Scale")
    portfolio = portfolio.sort_values("annual_opportunity_targeted", ascending=False).reset_index(drop=True)
    portfolio["opportunity_rank"] = np.arange(1, len(portfolio) + 1)

    # member_profile: CRM attributes, behaviour, and next best offer
    nbo = scores[scores.is_next_best_offer][["member_id", "promotion_id", "expected_net_margin"]].rename(
        columns={"promotion_id": "next_best_offer_id", "expected_net_margin": "next_best_offer_net_margin"})
    lm = raw["loyalty_members"]
    profile = lm[["member_id", "first_name", "last_name", "email", "enrolled_date"]].merge(
        features, on="member_id").merge(nbo, on="member_id", how="left")
    profile["next_best_offer_channel"] = profile.next_best_offer_id.map(promo.default_channel)

    featured = _featured_members(scores, profile)
    return {
        "promo_monthly": promo_monthly,
        "audience_tiers": tiers,
        "tier_backtest": backtest,
        "promo_portfolio": portfolio,
        "member_offer_scores": scores,
        "member_profile": profile,
        "featured_members": featured,
    }


def _featured_members(scores, profile):
    """Pick real members from the scores that illustrate each kind of decision."""
    s = scores.merge(profile[["member_id", "first_name", "last_name", "crm_segment", "visits"]], on="member_id")
    picks = [
        ("Morning commuter, coffee only", "PR01", "Persuadable", "expected_net_margin"),
        ("Morning commuter, already buys pastries", "PR01", "Sure Thing", "p_without_offer"),
        ("Lapsing regular", "PR02", "Persuadable", "expected_net_margin"),
        ("Afternoon snacker", "PR03", "Persuadable", "expected_net_margin"),
        ("Late-night regular", "PR05", "Sure Thing", "p_without_offer"),
    ]
    rows = []
    for label, pid, tier, key in picks:
        cand = s[(s.promotion_id == pid) & (s.tier == tier) & (s.visits >= 8)]
        if cand.empty:
            continue
        cand = cand.sort_values(key, ascending=False)
        pick = cand.iloc[min(len(cand) - 1, len(cand) // 10)]
        rows.append({"member_id": int(pick.member_id), "label": label,
                     "display": f"{pick.first_name} {pick.last_name[0]}. — {label}"})
    return pd.DataFrame(rows)


def feature_windows(pos_baskets, loyalty_members):
    """Training features (before the April policy change) and scoring features (the full year)."""
    return (member_features(pos_baskets, loyalty_members, HISTORY_START, PRE_END),
            member_features(pos_baskets, loyalty_members, HISTORY_START, DEMO_DATE))


def run_all(members=25_000, seed=711):
    """Full pipeline in pandas. Used by local_run.py; the notebooks run the same steps."""
    raw = simulate(members, seed)
    train_f, score_f = feature_windows(raw["pos_baskets"], raw["loyalty_members"])
    models = train_uplift(raw["offer_history"], train_f)
    scores = score_members(models, score_f)
    return raw, build_gold(raw, scores, score_f)


# Date columns in the raw tables, stored as DATE in Delta
RAW_DATE_COLS = {"loyalty_members": ["enrolled_date"], "offer_history": ["sent_date"]}
SAVE_CHUNK_ROWS = 500_000


def save_delta(spark, pdf, table, date_cols=()):
    """Write a pandas DataFrame to a Delta table in chunks, so large tables stay under message limits."""
    from pyspark.sql import functions as F

    spark.sql(f"DROP TABLE IF EXISTS {table}")
    for start in range(0, len(pdf), SAVE_CHUNK_ROWS):
        sdf = spark.createDataFrame(pdf.iloc[start:start + SAVE_CHUNK_ROWS])
        for c in date_cols:
            sdf = sdf.withColumn(c, F.to_date(F.col(c)))
        sdf.write.mode("append").saveAsTable(table)
    print(f"{table}: {len(pdf):,} rows")


# ---------------------------------------------------------------------------
# Story checks
# ---------------------------------------------------------------------------

def _per_month(df, col):
    return df[col].sum() / df.month_end.nunique()


def story_numbers(promo_monthly, promo_portfolio, tier_backtest):
    """The numbers the demo script quotes. Returns {label: value}."""
    pre = promo_monthly[promo_monthly.send_policy == SEND_POLICY_PRE]
    post = promo_monthly[promo_monthly.send_policy == SEND_POLICY_POST]
    spend_pre, spend_post = _per_month(pre, "discount_cost"), _per_month(post, "discount_cost")
    inc_pre, inc_post = _per_month(pre, "incremental_margin"), _per_month(post, "incremental_margin")
    pf = promo_portfolio.set_index("promotion_id")
    hero = pf.loc[HERO_PROMOTION]
    bt = tier_backtest[tier_backtest.promotion_id == HERO_PROMOTION].set_index("tier")
    return {
        "Monthly discount spend, Jan-Mar": spend_pre,
        "Monthly discount spend, Apr-Sep": spend_post,
        "Discount spend growth after April": spend_post / spend_pre - 1,
        "Monthly incremental margin, Jan-Mar": inc_pre,
        "Monthly incremental margin, Apr-Sep": inc_post,
        "Incremental margin, Apr-Sep minus half of Jan-Mar": inc_post - 0.5 * inc_pre,
        "Coffee + Croissant redemption rate, Apr-Sep": hero.redemption_rate_apr_sep,
        "Coffee + Croissant measured uplift, Apr-Sep": hero.measured_uplift_apr_sep,
        "Coffee + Croissant redemptions that would happen anyway": hero.redemptions_that_would_happen_anyway,
        "Coffee + Croissant net margin per send, blast": hero.blast_net_margin_per_send,
        "Coffee + Croissant net margin per send, targeted": hero.targeted_net_margin_per_send,
        "Coffee + Croissant backtest uplift, Persuadable": bt.at["Persuadable", "measured_uplift"],
        "Coffee + Croissant backtest uplift, Sure Thing": bt.at["Sure Thing", "measured_uplift"],
        "Portfolio net margin per send, blast": promo_portfolio.blast_net_margin_per_send.sum(),
        "Portfolio net margin per send, targeted": promo_portfolio.targeted_net_margin_per_send.sum(),
        "Coffee + Croissant is the top opportunity": float(promo_portfolio.iloc[0].promotion_id == HERO_PROMOTION),
    }


STORY_RANGES = {
    "Discount spend growth after April": (1.5, 5.0),
    "Monthly incremental margin, Jan-Mar": (0.0, 1e9),
    "Incremental margin, Apr-Sep minus half of Jan-Mar": (-1e9, 0.0),
    "Coffee + Croissant redemption rate, Apr-Sep": (0.30, 0.50),
    "Coffee + Croissant measured uplift, Apr-Sep": (0.08, 0.18),
    "Coffee + Croissant redemptions that would happen anyway": (0.55, 0.85),
    "Coffee + Croissant net margin per send, blast": (-1e9, 0.0),
    "Coffee + Croissant net margin per send, targeted": (0.0, 1e9),
    "Coffee + Croissant backtest uplift, Persuadable": (0.12, 0.35),
    "Coffee + Croissant backtest uplift, Sure Thing": (-0.05, 0.08),
    "Portfolio net margin per send, blast": (-1e9, 0.0),
    "Portfolio net margin per send, targeted": (0.0, 1e9),
    "Coffee + Croissant is the top opportunity": (1.0, 1.0),
}


def story_checks(numbers):
    """Print PASS or CHECK for each story number with a target range, INFO for the rest."""
    for label, value in numbers.items():
        if label not in STORY_RANGES:
            print(f"[INFO] {label}: {value:,.3f}")
            continue
        low, high = STORY_RANGES[label]
        print(f"[{'PASS' if low <= value <= high else 'CHECK'}] {label}: {value:,.3f}")
