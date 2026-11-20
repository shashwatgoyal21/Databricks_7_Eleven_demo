# Genie space: Promotion Performance

## Setup

1. **Genie > New**. Name: `Promotion Performance`. Warehouse: the same Pro or Serverless warehouse as the app and dashboard.
2. Add these data sources from `workspace.nbo_demo` (or your catalog and schema):
   - `metrics_promotions` (metric view)
   - `promo_portfolio`
   - `audience_tiers`
   - `tier_backtest`
   - `promotions`
3. Paste the instructions below into **Instructions**.
4. Add the example questions and SQL as **SQL queries** (trusted examples).
5. Share the space with `loyalty_leadership` and the four `marketing_*` groups.

Don't add `loyalty_members`, `member_profile`, `member_offer_scores`, or `pos_baskets`. Genie answers from aggregates only.

## Instructions

```text
You answer promotion performance questions for loyalty and marketing leaders at a fictional convenience retailer.

Data:
- metrics_promotions is the source of truth for offers sent, redemptions, redemption rate, holdout conversion rate, measured lift, discount spend, incremental conversions, and incremental margin. Use MEASURE() for every metric.
- Every send holds back 10% of the audience. measured_lift = redemption rate minus holdout conversion rate. It is the share of recipients the offer actually moved. Show it in percentage points.
- redemptions_that_would_happen_anyway = holdout conversion rate / redemption rate. Show it as a percentage.
- incremental_margin already subtracts the discount cost. Negative means the promotion lost money.
- send_policy splits the year: 'Curated sends (Jan-Mar)' versus 'All eligible (Apr-Sep)'. On 2026-04-01 every offer started going to everyone eligible.
- promo_portfolio has one row per promotion as of 2026-09-30: eligible members, persuadable members, net margin per send if sent to all eligible (blast_net_margin_per_send) versus only to persuadables (targeted_net_margin_per_send), and the recommendation.
- audience_tiers breaks each promotion's eligible members into Persuadable, Sure Thing, Lost Cause, and Low ROI.
- tier_backtest shows measured lift by model tier on the Apr-Sep sends. It is the evidence that the tiers are right.

A "sure thing" is a shopper who would buy the promoted item without the offer. Discounts to sure things are pure cost.

When asked why spend or margin changed, compare send_policy periods first, then break down by promotion, then compare redemption rate with measured lift for the promotion with the largest gap.

Never discuss individual members.
```

## Example questions and SQL

**Why did discount spend go up after April but incremental margin go down?**

```sql
SELECT send_policy, promotion,
       MEASURE(discount_spend) AS discount_spend,
       MEASURE(incremental_margin) AS incremental_margin,
       MEASURE(redemption_rate) AS redemption_rate,
       MEASURE(measured_lift) AS measured_lift,
       MEASURE(redemptions_that_would_happen_anyway) AS would_happen_anyway
FROM workspace.nbo_demo.metrics_promotions
GROUP BY send_policy, promotion
ORDER BY send_policy, incremental_margin
```

**Which promotion has the biggest gap between redemption rate and real lift?**

```sql
SELECT promotion,
       MEASURE(redemption_rate) AS redemption_rate,
       MEASURE(measured_lift) AS measured_lift,
       MEASURE(redemptions_that_would_happen_anyway) AS would_happen_anyway
FROM workspace.nbo_demo.metrics_promotions
WHERE send_policy = 'All eligible (Apr-Sep)'
GROUP BY promotion
ORDER BY would_happen_anyway DESC
```

**What would targeting only persuadable shoppers be worth?**

```sql
SELECT short_name, eligible_members, persuadable_members,
       blast_net_margin_per_send, targeted_net_margin_per_send,
       annual_gain_vs_blast, status
FROM workspace.nbo_demo.promo_portfolio
ORDER BY opportunity_rank
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

## Demo question

Ask exactly: *"Why did discount spend go up after April but incremental margin go down?"* The answer should show spend roughly tripling, incremental margin turning negative, and name Coffee + Croissant: high redemption rate, but about two thirds of redemptions would have happened anyway.
