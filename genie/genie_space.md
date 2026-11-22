# Genie space: In-Store NBO Performance

While a shopper is in the store, the system picks the promotion most likely to get that person to add to their basket and sends it to them right then. This Genie space lets the data and AI engineering team ask plain-English questions about what that decision path did and whether the model is right.

## Setup

1. **Genie > New**. Name: `In-Store NBO Performance`. Warehouse: the same Pro or Serverless warehouse as the app and dashboard.
2. Add these data sources from `workspace.nbo_demo` (or your catalog and schema):
   - `offer_decisions`
   - `nbo_decision_payload` (endpoint inference table, after the first request)
   - `metrics_promotions` (metric view)
   - `tier_backtest`
   - `promo_portfolio`
   - `promotions`
3. Paste the instructions below into **Instructions**.
4. Add the example questions and SQL as **SQL queries** (trusted examples).
5. Share the space with `nbo_platform` and the four `nbo_region_*` groups.

Don't add `loyalty_members`, `member_profile`, `member_offer_scores`, or `pos_baskets`. Genie answers from decisions and aggregates only.

## Instructions

```text
You answer questions about a real-time, in-store Next Best Offer system at a fictional convenience retailer. The audience is data engineering and AI engineering.

How the system works:
- A loyalty shopper who shares their location with the app triggers a check-in when they walk into a store ("Shared location: entered store"). Shoppers without the app trigger one when they scan their loyalty ID at the pin-pad.
- The nbo-decision Model Serving endpoint looks up the shopper's features online, scores an uplift model for every promotion (likelihood to buy with and without the offer), applies live rules (daypart, item already scanned, store has fresh bakery, days since last visit), and returns one offer or no offer. 10% of check-ins with an offer are held out.

Data:
- offer_decisions: one row per check-in on the live day (2026-09-30). decision is 'Offer served', 'No offer', or 'Holdout (no offer shown)'. promotion_id is the offer chosen. reason explains the decision.
- nbo_decision_payload: every request to the endpoint. execution_duration_ms is server-side latency. status_code 200 is success.
- metrics_promotions: monthly in-store offer history Jan-Sep 2026 with a 10% holdout. Use MEASURE() for every metric. send_policy is 'Curated pilot (Jan-Mar)' or 'Static rules, all eligible (Apr-Sep)'. From 2026-04-01 a static rules engine showed every eligible offer at every check-in.
- measured_lift = redemption rate minus holdout conversion rate, in percentage points. redemptions_that_would_happen_anyway = holdout conversion rate / redemption rate.
- tier_backtest: measured lift by model tier on Apr-Sep offers. It is the evidence the model is right.
- promo_portfolio: per promotion, net margin per month under static rules (blast_net_margin_per_send) versus the model (targeted_net_margin_per_send).

A "Sure Thing" buys the promoted item without the offer, so the discount is pure cost and the system suppresses it. A "Persuadable" buys because of the offer.

Never discuss individual shoppers.
```

## Example questions and SQL

**How many check-ins got an offer today, and why did the rest not?**

```sql
SELECT decision, reason, COUNT(*) AS check_ins
FROM workspace.nbo_demo.offer_decisions
GROUP BY ALL
ORDER BY check_ins DESC
```

**Which offers did we push, by daypart?**

```sql
SELECT p.short_name AS promotion, d.daypart, COUNT(*) AS offers
FROM workspace.nbo_demo.offer_decisions d
JOIN workspace.nbo_demo.promotions p USING (promotion_id)
WHERE d.decision = 'Offer served'
GROUP BY ALL
ORDER BY offers DESC
```

**What is the endpoint's p95 latency?**

```sql
SELECT COUNT(*) AS requests,
       PERCENTILE(execution_duration_ms, 0.5) AS p50_ms,
       PERCENTILE(execution_duration_ms, 0.95) AS p95_ms,
       COUNT_IF(status_code <> 200) AS errors
FROM workspace.nbo_demo.nbo_decision_payload
```

**Does the model's tiering hold up against the holdout?**

```sql
SELECT p.short_name, b.tier, b.treatment_sends, b.holdout_sends,
       b.treatment_conversion_rate, b.holdout_conversion_rate, b.measured_uplift
FROM workspace.nbo_demo.tier_backtest b
JOIN workspace.nbo_demo.promotions p USING (promotion_id)
WHERE b.holdout_sends >= 30
ORDER BY p.short_name, b.measured_uplift DESC
```

**Why not just use static rules?**

```sql
SELECT send_policy, promotion,
       MEASURE(discount_spend) AS discount_spend,
       MEASURE(incremental_margin) AS incremental_margin,
       MEASURE(redemptions_that_would_happen_anyway) AS would_happen_anyway
FROM workspace.nbo_demo.metrics_promotions
GROUP BY send_policy, promotion
ORDER BY send_policy, incremental_margin
```

## Demo question

Ask exactly: *"How many check-ins got an offer today, and why did the rest not?"* The answer should show roughly one in five check-ins getting an offer, and most of the rest suppressed because no offer fits the moment or the shopper would buy anyway.
