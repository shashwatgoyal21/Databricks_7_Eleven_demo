# In-Store NBO dashboard layout

Build in **AI/BI Dashboards** on a Pro or Serverless SQL warehouse. Create the datasets from `datasets.sql` first, then add widgets in this order. This is where the data and AI engineering team tracks the real-time decision path: what it decided, how fast, and whether the model is right.

`nbo_decision_payload` is created by the endpoint's inference table the first time the endpoint is called. Run notebook 06 (it sends one check-in) or click through the app before building page 1.

## Page 1: Real-time decisions

| Row | Widget | Dataset | Settings |
| --- | --- | --- | --- |
| 1 | Counter: **Check-ins decided** | `kpi_live_day` | Value `check_ins` |
| 1 | Counter: **Offers pushed** | `kpi_live_day` | Value `offers_served` |
| 1 | Counter: **Offer rate** | `kpi_live_day` | Value `offer_rate`, percent |
| 1 | Counter: **Suppressed, no offer moves them** | `kpi_live_day` | Value `suppressed` |
| 1 | Counter: **Endpoint p95 latency** | `endpoint_latency` | Value `MAX(p95_ms)`, suffix ms |
| 2 | Bar chart: **Decisions by hour** | `decisions_by_hour` | X `hour`, Y `check_ins`, color `decision`, stacked |
| 2 | Line chart: **Endpoint latency p50 / p95** | `endpoint_latency` | X `minute`, Y `p50_ms` and `p95_ms` |
| 3 | Bar chart: **Offers pushed by promotion and daypart** | `offers_by_promotion` | X `promotion`, Y `offers`, color `daypart` |
| 3 | Bar chart: **Why no offer** | `why_no_offer` | X `reason`, Y `check_ins` |

## Page 2: Is the model right?

| Row | Widget | Dataset | Settings |
| --- | --- | --- | --- |
| 1 | Bar chart: **Measured lift by model tier (holdout)** | `tier_backtest` | X `tier`, Y `measured_uplift` as percent, color `tier`, small multiples by `promotion` |
| 1 | Line chart: **Static rules: discount spend vs incremental margin** | `rules_vs_model_trend` | X `month_end`, Y `usd`, color `measure` |
| 2 | Bar chart: **Redemption rate vs measured lift under static rules** | `redemption_vs_lift` | X `promotion`, Y `rate` as percent, color `measure`, grouped |
| 2 | Table: **Static rules vs model, per promotion** | `model_vs_rules` | Rates as percent, money as currency |

## What the presenter should see

- Page 1: morning and afternoon peaks of pushed offers, most check-ins correctly get no offer, and endpoint latency in the tens of milliseconds.
- Page 2: Persuadables show large measured lift, Sure Things almost none. Under static rules, spend tripled from April while incremental margin went negative.
- Signed in as a member of one `nbo_region_*` group, every chart shows that region only.
