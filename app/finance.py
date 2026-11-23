"""Finance assumptions and the network-level P&L the agent and the finance report show.

Nothing here is a hard-coded result. Every figure is computed from stored history (offer_performance,
compute_cost) and scaled to the network with the assumptions in the `finance_assumptions` table, which
finance owns and can edit in Unity Catalog. DEFAULTS only seed that table on the first build.
"""

import pandas as pd
import streamlit as st

import data

DEFAULTS = {
    # key: (value, unit, description)
    "network_stores": (13000, "stores", "Stores the offer engine would run in. Results are scaled from the pilot "
                                        "stores in the data to this count."),
    "hurdle_rate": (0.101, "ratio", "Return on invested capital each offer program must clear."),
    "promoted_item_gross_margin": (0.45, "ratio", "Gross margin rate on promoted items, used to turn incremental "
                                                 "margin into incremental sales (top line)."),
    "cannibalization_rate": (0.15, "ratio", "Share of incremental units that would have been bought as another "
                                           "item in the same basket. Removed from incremental margin."),
    "platform_cost_annual": (2_000_000, "USD/yr", "Annual run cost plus amortized build cost of the offer engine "
                                                  "(engineering, licenses, integration), outside per-call compute."),
}


@st.cache_data(ttl=300)
def assumptions():
    """{key: value}. From the finance_assumptions table on Databricks; DEFAULTS in local preview."""
    vals = {k: float(v[0]) for k, v in DEFAULTS.items()}
    if data.LOCAL:
        return vals
    try:
        rows = data._query(f"SELECT key, value FROM {data.SCHEMA}.finance_assumptions")
        vals.update({k: float(v) for k, v in zip(rows.key, rows.value)})
    except Exception:
        pass
    return vals


def pilot_scope():
    """Stores and days covered by the stored outcomes, so results scale to network and year."""
    p = data.table("offer_performance")
    stores = data.table("stores")
    return max(len(stores), 1), max(p.decision_date.nunique() if not p.empty else 1, 1)


def scale_to_network_year():
    a = assumptions()
    n_stores, days = pilot_scope()
    return a["network_stores"] / n_stores * 365 / days


def network_pnl(by="promotion_id"):
    """Annual network P&L from stored outcomes. One row per `by` value plus totals.

    Top line: incremental sales. Bottom line: operating profit impact after discounts, compute and the
    platform cost. ROIC = operating profit impact / capital deployed (discounts + compute + platform cost).
    """
    p = data.table("offer_performance")
    if p.empty:
        return pd.DataFrame(), {}
    a = assumptions()
    k = scale_to_network_year()
    g = p.groupby(by)[["offers_served", "holdout_checkins", "delivered", "accepted", "incremental_margin",
                       "discount_cost", "compute_cost_usd"]].sum()
    decisions = g.offers_served + g.holdout_checkins
    t = pd.DataFrame(index=g.index)
    t["acceptance_rate"] = g.accepted / g.delivered.where(g.delivered > 0)
    t["incremental_margin"] = g.incremental_margin * (1 - a["cannibalization_rate"]) * k
    t["incremental_sales"] = t.incremental_margin / a["promoted_item_gross_margin"]
    t["discount_cost"] = g.discount_cost * k
    t["compute_cost"] = g.compute_cost_usd * k
    t["platform_cost"] = a["platform_cost_annual"] * decisions / max(decisions.sum(), 1)
    t["gross_profit_after_discount"] = t.incremental_margin - t.discount_cost
    t["operating_profit"] = t.gross_profit_after_discount - t.compute_cost - t.platform_cost
    t["capital"] = t.discount_cost + t.compute_cost + t.platform_cost
    t["roic"] = t.operating_profit / t.capital.where(t.capital > 0)
    t["cost_per_decision"] = g.compute_cost_usd / decisions.clip(lower=1)
    t["clears_hurdle"] = t.roic >= a["hurdle_rate"]
    s = t[["incremental_sales", "incremental_margin", "discount_cost", "compute_cost", "platform_cost",
           "gross_profit_after_discount", "operating_profit", "capital"]].sum()
    total = s.to_dict()
    total["roic"] = s.operating_profit / s.capital if s.capital else 0.0
    total["cost_per_decision"] = float(p.compute_cost_usd.sum() / max((p.offers_served + p.holdout_checkins).sum(), 1))
    total["acceptance_rate"] = float(p.accepted.sum() / max(p.delivered.sum(), 1))
    total["hurdle_rate"] = a["hurdle_rate"]
    total["network_stores"] = a["network_stores"]
    return t.reset_index(), total
