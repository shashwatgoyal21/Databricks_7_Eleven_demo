# Promotion Performance dashboard layout

Build in **AI/BI Dashboards** on a Pro or Serverless SQL warehouse. Create the datasets from `datasets.sql` first, then add widgets in this order. The dashboard is the leadership view; the app is where marketers act.

## Page 1: Is promo spend working?

| Row | Widget | Dataset | Settings |
| --- | --- | --- | --- |
| 1 | Counter: **Monthly discount spend** | `kpi_spend_and_margin` | Value `monthly_discount_spend`, filter `send_policy = 'All eligible (Apr-Sep)'`, format currency |
| 1 | Counter: **Monthly incremental margin** | `kpi_spend_and_margin` | Value `monthly_incremental_margin`, same filter, format currency |
| 1 | Counter: **Coffee + Croissant redemptions that would happen anyway** | `kpi_coffee_anyway` | Value `would_happen_anyway`, format percent, 0 decimals |
| 1 | Counter: **Annual gain from uplift targeting** | `kpi_targeting_gain` | Value `annual_gain_vs_blast`, format currency |
| 2 | Line chart: **Discount spend vs incremental margin** | `spend_vs_margin_trend` | X `month_end`, Y `usd`, color `measure`; Discount spend orange, Incremental margin green |

## Page 2: Where is the waste?

| Row | Widget | Dataset | Settings |
| --- | --- | --- | --- |
| 1 | Bar chart: **Redemption rate vs measured lift, Apr–Sep** | `redemption_vs_lift` | X `promotion`, Y `rate` as percent, color `measure`, grouped |
| 1 | Bar chart: **Incremental margin by region, Apr–Sep** | `margin_by_region` | X `region`, Y `incremental_margin`, color `promotion`, stacked |
| 2 | Bar chart: **Measured lift by model tier** | `tier_backtest` | X `tier`, Y `measured_uplift` as percent, color `tier`, small multiples by `promotion` |
| 2 | Table: **Promotion portfolio** | `portfolio` | Rates as percent, money as currency |

## What the presenter should see

- Page 1: spend roughly triples from April while incremental margin drops below zero.
- Page 2: Coffee + Croissant has the tallest redemption bar and a short lift bar. Persuadables show large measured lift, sure things almost none.
- Signed in as a regional marketing manager, the region chart shows one region only.
