"""Real-time Next Best Offer decision path.

While a shopper is in the store, pick the promotion most likely to get that person to add to their
basket and send it to them right then.

Input per check-in event: live context (store, daypart, first item scanned, days since last visit)
joined to the member's precomputed uplift scores (one row per promotion: likelihood to buy with and
without the offer). Output: one offer, or no offer, with the reason. Pure pandas/numpy so the same
code runs in the app, the streaming decision job, and a Model Serving pyfunc.
"""

import numpy as np
import pandas as pd

LAPSED_AFTER_DAYS = 14
WINBACK_WINDOW_DAYS = 90

# Promotion economics: (unit margin on an incremental purchase, discount cost per redemption)
PROMO_ECONOMICS = {"PR01": (3.20, 1.50), "PR02": (3.40, 1.10), "PR03": (2.80, 0.75), "PR04": (2.30, 0.80),
                   "PR05": (1.40, 1.00)}

# Shopper features the uplift model reads (looked up online by member_id at serving time)
MODEL_FEATURES = [
    "visits_per_active_week", "morning_share", "midday_share", "afternoon_share", "evening_share",
    "late_night_share", "coffee_rate", "pastry_rate", "pastry_with_coffee_rate", "roller_grill_rate",
    "sandwich_rate", "energy_drink_rate", "cold_dispensed_rate", "avg_basket_value",
    "tenure_months", "app_user",
]
# The check-in the caller sends. Only member_id, store_id and event_ts are required; first_scan ("" if
# unknown) and days_since_prev_visit (-1 if unknown) add context when the caller has it.
CHECKIN_FIELDS = ["member_id", "store_id", "event_ts", "first_scan", "days_since_prev_visit"]
EVENT_FIELDS = ["event_id", "event_ts", "member_id", "store_id", "region", "city", "store_has_fresh_bakery",
                "trigger", "daypart", "first_scan", "first_scan_label", "days_since_prev_visit", "app_user"]

# Decision thresholds applied to model scores
MIN_UPLIFT = 0.04
MIN_NET_MARGIN = 0.05
SURE_THING_BASELINE = 0.35
LOST_CAUSE_RESPONSE = 0.10

LIVE_HOLDOUT_MOD = 10  # event_id % 10 == 0 is held out
OFFER_MESSAGE = {
    "PR01": "Add a warm croissant to your coffee for $1.50 off",
    "PR02": "Welcome back: a free medium Slurpee is on us today",
    "PR03": "Grab a second taquito at 50% off before you check out",
    "PR04": "2x points on any fresh sandwich, right now",
    "PR05": "$1 off any energy drink on this visit",
}
PUSH_TITLE = {
    "PR01": "Your coffee is better with a croissant",
    "PR02": "Welcome back",
    "PR03": "Afternoon snack deal",
    "PR04": "Lunch is on points",
    "PR05": "Late-night deal",
}
CONTEXT_RULE = {
    "PR01": "Morning, coffee already scanned, store has fresh bakery",
    "PR02": "First visit in 14 to 90 days",
    "PR03": "Afternoon visit",
    "PR04": "Midday visit",
    "PR05": "Late-night visit",
}


def assign_tier(s):
    """Persuadable / Sure Thing / Lost Cause / Low ROI from the two response scores."""
    return np.select(
        [(s.expected_net_margin > MIN_NET_MARGIN) & (s.uplift >= MIN_UPLIFT),
         (s.p_without_offer >= SURE_THING_BASELINE) & (s.uplift < MIN_UPLIFT + 0.02),
         s.p_with_offer < LOST_CAUSE_RESPONSE],
        ["Persuadable", "Sure Thing", "Lost Cause"], default="Low ROI")


def behaviour_eligible(f):
    """Which promotions a shopper qualifies for from their behaviour (before live context).
    Columns per promotion id, aligned to f's index."""
    opt = f.marketing_opt_in.astype(bool)
    return pd.DataFrame({
        "PR01": (f.coffee_rate >= 0.35) & (f.morning_share >= 0.40),
        "PR02": f.visits_per_active_week > 0,
        "PR03": f.afternoon_share >= 0.30,
        "PR04": f.midday_share >= 0.30,
        "PR05": f.late_night_share >= 0.25,
    }, index=f.index).mul(opt, axis=0).astype(bool)


def score_requests(requests, models):
    """Real-time scoring: requests carry the check-in plus the shopper's looked-up features.
    models: {promotion_id: {"treated": clf, "control": clf}}. Returns member x promotion scores."""
    X = requests[MODEL_FEATURES].astype(float)
    elig = behaviour_eligible(requests)
    frames = []
    for pid, m in models.items():
        p_t = m["treated"].predict_proba(X)[:, 1]
        p_c = m["control"].predict_proba(X)[:, 1]
        uplift = np.clip(p_t - p_c, -0.2, 0.6)
        margin, discount = PROMO_ECONOMICS[pid]
        frames.append(pd.DataFrame({
            "member_id": requests.member_id.to_numpy(), "promotion_id": pid,
            "eligible": elig[pid].to_numpy(), "p_without_offer": p_c, "p_with_offer": p_t, "uplift": uplift,
            "expected_net_margin": uplift * margin - p_t * discount,
        }))
    return pd.concat(frames, ignore_index=True).drop_duplicates(["member_id", "promotion_id"])


SCAN_LABEL = {"coffee": "Hot coffee", "sandwich": "Fresh sandwich", "roller_grill": "Roller grill item",
              "energy_drink": "Energy drink", "cold_dispensed": "Slurpee", "packaged_beverage": "Bottled drink",
              "snacks": "Snack", "": "Nothing yet"}


def checkin_id(member_id, event_ts):
    """Stable id per shopper and minute, so the same check-in gets the same id (and the same 10% holdout
    draw) in the batch build, the stream, and the endpoint."""
    minute = pd.to_datetime(event_ts).astype("datetime64[ns]").astype("int64") // 60_000_000_000
    return ((pd.Series(member_id).astype("int64").to_numpy() * 100_003 + minute.to_numpy()) % 1_000_000_007
            ).astype("int64")


def daypart_of(ts):
    h = pd.to_datetime(ts).dt.hour
    return pd.Series(np.select([h.between(5, 9), h.between(10, 13), h.between(14, 17), h.between(18, 21)],
                               ["Morning", "Midday", "Afternoon", "Evening"], default="Late Night"), index=ts.index)


def complete_checkin(r):
    """Fill everything the decision needs from a minimal check-in (member_id, store_id, event_ts) plus the
    looked-up features. Callers only have to send what their location / POS stack already knows."""
    r = r.copy()
    r["event_ts"] = pd.to_datetime(r.event_ts)
    if "event_id" not in r:
        r["event_id"] = checkin_id(r.member_id, r.event_ts)
    if "daypart" not in r or r.daypart.isna().all():
        r["daypart"] = daypart_of(r.event_ts)
    r["first_scan"] = r.get("first_scan", pd.Series("", index=r.index)).fillna("")
    r["first_scan_label"] = r.first_scan.map(SCAN_LABEL).fillna(r.first_scan)
    if "store_has_fresh_bakery" not in r:
        r["store_has_fresh_bakery"] = r.get("has_fresh_bakery", pd.Series(True, index=r.index)).fillna(True)
    gap = r.get("days_since_prev_visit", pd.Series(-1, index=r.index)).fillna(-1).astype(int)
    looked_up = r.get("days_since_last_visit", pd.Series(999, index=r.index)).fillna(999).astype(int)
    r["days_since_prev_visit"] = np.where(gap >= 0, gap, looked_up)
    for col, default in [("region", ""), ("city", ""), ("trigger", "Shared location: entered store")]:
        if col not in r:
            r[col] = default
        r[col] = r[col].fillna(default)
    return r


def score_and_decide(requests, models):
    """The full real-time decision for a batch of check-ins: score every promotion, apply live rules,
    arbitrate, hold out 10%. This is what the Model Serving endpoint runs per request."""
    r = complete_checkin(requests)
    scores = score_requests(r, models)
    return decide(offer_candidates(r[EVENT_FIELDS], scores, r[["member_id", "marketing_opt_in"]]))


def context_ok(c):
    """Live context rule per candidate row (event x promotion)."""
    return np.select(
        [c.promotion_id == "PR01", c.promotion_id == "PR02", c.promotion_id == "PR03",
         c.promotion_id == "PR04", c.promotion_id == "PR05"],
        [(c.daypart == "Morning") & (c.first_scan == "coffee") & c.store_has_fresh_bakery.astype(bool),
         c.days_since_prev_visit.between(LAPSED_AFTER_DAYS, WINBACK_WINDOW_DAYS),
         c.daypart == "Afternoon",
         c.daypart == "Midday",
         c.daypart == "Late Night"],
        default=False).astype(bool)


def offer_candidates(events, scores, opt_in):
    """Every event x promotion, with the member's scores, eligibility, live context check and tier.
    opt_in: DataFrame with member_id and marketing_opt_in."""
    opt = opt_in.drop_duplicates("member_id").set_index("member_id").marketing_opt_in.astype(bool)
    sc = scores[["member_id", "promotion_id", "eligible", "p_without_offer", "p_with_offer", "uplift",
                 "expected_net_margin"]]
    c = events.merge(sc, on="member_id", how="inner")
    # Win-back eligibility comes from the live visit gap, not last night's batch
    is_wb = c.promotion_id == "PR02"
    c["eligible"] = np.where(is_wb, opt.reindex(c.member_id).to_numpy(), c.eligible.astype(bool))
    c["context_ok"] = context_ok(c)
    c["tier"] = assign_tier(c)
    c["context_rule"] = c.promotion_id.map(CONTEXT_RULE)
    c["candidate"] = c.eligible & c.context_ok & (c.tier == "Persuadable")
    return c


def decide(candidates):
    """One decision per event: the Persuadable candidate with the highest expected net margin."""
    c = candidates
    best = (c[c.candidate].sort_values("expected_net_margin", ascending=False)
            .drop_duplicates("event_id").set_index("event_id"))
    live = c[c.eligible & c.context_ok]
    live_tier = live.groupby("event_id").tier.agg(lambda t: ", ".join(sorted(set(t))))
    ev = c.drop_duplicates("event_id").set_index("event_id")[
        ["event_ts", "member_id", "store_id", "region", "city", "trigger", "daypart", "first_scan_label",
         "days_since_prev_visit", "app_user"]]
    out = ev.join(best[["promotion_id", "p_without_offer", "p_with_offer", "uplift", "expected_net_margin"]])
    out["holdout"] = (out.index.to_numpy() % LIVE_HOLDOUT_MOD) == 0
    has = out.promotion_id.notna()
    out["decision"] = np.select([has & out.holdout, has], ["Holdout (no offer shown)", "Offer served"],
                                default="No offer")
    out["offer_message"] = np.where(has & ~out.holdout, out.promotion_id.map(OFFER_MESSAGE), None)
    out["channel"] = np.where(has & ~out.holdout,
                              np.where(out.app_user, "App push + POS pin-pad", "POS pin-pad"), None)
    lt = live_tier.reindex(out.index)
    out["reason"] = np.select(
        [has & out.holdout, has, lt.notna()],
        ["Held out for measurement", "Highest expected net margin among offers that move this shopper",
         "Offers that fit this moment would not change what this shopper buys (" + lt.fillna("") + ")"],
        default="No offer fits this moment")
    return out.reset_index()


def push_payload(decision, device_token=None):
    """iOS push for a served offer, in Apple Push Notification service (APNs) shape. None if no offer.
    In production the device token comes from the shopper's app registration; the payload is sent to
    APNs or the retailer's push provider."""
    if decision.get("decision") != "Offer served" or not decision.get("promotion_id"):
        return None
    pid = decision["promotion_id"]
    return {
        "aps": {"alert": {"title": PUSH_TITLE.get(pid, "An offer for you"), "body": OFFER_MESSAGE[pid]},
                "sound": "default", "category": "NBO_OFFER", "interruption-level": "time-sensitive"},
        "offer_id": pid,
        "event_id": int(decision["event_id"]),
        "store_id": int(decision["store_id"]),
        "device_token": device_token,
    }

