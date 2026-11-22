-- AI/BI dashboard datasets for the real-time in-store Next Best Offer demo.
-- Replace workspace.nbo_demo if you deployed to a different catalog or schema.
-- Create one dataset per block in the dashboard's Data tab, using the name in the header.

-- =====================================================================
-- Page 1 · "Real-time decisions"
-- =====================================================================

-- Dataset: kpi_live_day  (counters)
SELECT COUNT(*)                                                       AS check_ins,
       COUNT_IF(decision = 'Offer served')                            AS offers_served,
       COUNT_IF(decision = 'Offer served') / COUNT(*)                 AS offer_rate,
       COUNT_IF(decision = 'No offer')                                AS suppressed,
       COUNT_IF(decision LIKE 'Holdout%')                             AS held_out,
       COUNT_IF(trigger = 'Shared location: entered store') / COUNT(*) AS share_via_app_location
FROM workspace.nbo_demo.offer_decisions;

-- Dataset: decisions_by_hour  (stacked bar: x = hour, y = check_ins, color = decision)
SELECT HOUR(event_ts) AS hour, decision, COUNT(*) AS check_ins
FROM workspace.nbo_demo.offer_decisions
GROUP BY ALL;

-- Dataset: offers_by_promotion  (bar: x = promotion, y = offers)
SELECT p.short_name AS promotion, d.daypart, COUNT(*) AS offers
FROM workspace.nbo_demo.offer_decisions d
JOIN workspace.nbo_demo.promotions p USING (promotion_id)
WHERE d.decision = 'Offer served'
GROUP BY ALL;

-- Dataset: why_no_offer  (bar: x = reason, y = check_ins)
SELECT reason, COUNT(*) AS check_ins
FROM workspace.nbo_demo.offer_decisions
WHERE decision = 'No offer'
GROUP BY ALL;

-- Dataset: endpoint_latency  (line: x = minute, y = p50_ms and p95_ms; counter: requests)
-- Every request to the nbo-decision endpoint, logged by its AI Gateway inference table.
SELECT DATE_TRUNC('MINUTE', request_time)        AS minute,
       COUNT(*)                                   AS requests,
       PERCENTILE(execution_duration_ms, 0.5)     AS p50_ms,
       PERCENTILE(execution_duration_ms, 0.95)    AS p95_ms,
       COUNT_IF(status_code <> 200)               AS errors
FROM workspace.nbo_demo.nbo_decision_payload
GROUP BY ALL;

-- =====================================================================
-- Page 2 · "Is the model right?"
-- =====================================================================

-- Dataset: tier_backtest  (bar: x = tier, y = measured_uplift, small multiples by promotion)
SELECT p.short_name AS promotion, b.tier, b.measured_uplift, b.treatment_sends, b.holdout_sends
FROM workspace.nbo_demo.tier_backtest b
JOIN workspace.nbo_demo.promotions p USING (promotion_id)
WHERE b.holdout_sends >= 30;

-- Dataset: rules_vs_model_trend  (line: x = month_end, y = usd, color = measure)
SELECT month_end, 'Discount spend' AS measure, MEASURE(discount_spend) AS usd
FROM workspace.nbo_demo.metrics_promotions
GROUP BY month_end
UNION ALL
SELECT month_end, 'Incremental margin' AS measure, MEASURE(incremental_margin) AS usd
FROM workspace.nbo_demo.metrics_promotions
GROUP BY month_end;

-- Dataset: redemption_vs_lift  (grouped bar: x = promotion, y = rate, color = measure)
SELECT promotion, 'Redemption rate' AS measure, MEASURE(redemption_rate) AS rate
FROM workspace.nbo_demo.metrics_promotions
WHERE send_policy = 'Static rules, all eligible (Apr-Sep)'
GROUP BY promotion
UNION ALL
SELECT promotion, 'Measured lift' AS measure, MEASURE(measured_lift) AS rate
FROM workspace.nbo_demo.metrics_promotions
WHERE send_policy = 'Static rules, all eligible (Apr-Sep)'
GROUP BY promotion;

-- Dataset: model_vs_rules  (table)
SELECT short_name AS promotion, eligible_members, persuadable_members,
       redemption_rate_apr_sep, measured_uplift_apr_sep,
       blast_net_margin_per_send AS net_margin_per_month_static_rules,
       targeted_net_margin_per_send AS net_margin_per_month_model,
       annual_gain_vs_blast
FROM workspace.nbo_demo.promo_portfolio
ORDER BY opportunity_rank;
