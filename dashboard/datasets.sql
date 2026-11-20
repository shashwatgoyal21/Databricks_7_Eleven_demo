-- AI/BI dashboard datasets for the Next Best Offer demo.
-- Replace workspace.nbo_demo if you deployed to a different catalog or schema.
-- Create one dataset per block in the dashboard's Data tab, using the name in the header.

-- =====================================================================
-- Page 1 · "Is promo spend working?"
-- =====================================================================

-- Dataset: kpi_spend_and_margin
SELECT send_policy,
       MEASURE(monthly_discount_spend) AS monthly_discount_spend,
       MEASURE(monthly_incremental_margin) AS monthly_incremental_margin
FROM workspace.nbo_demo.metrics_promotions
GROUP BY send_policy;

-- Dataset: kpi_coffee_anyway
SELECT MEASURE(redemption_rate) AS redemption_rate,
       MEASURE(redemptions_that_would_happen_anyway) AS would_happen_anyway
FROM workspace.nbo_demo.metrics_promotions
WHERE promotion_id = 'PR01' AND send_policy = 'All eligible (Apr-Sep)';

-- Dataset: kpi_targeting_gain
SELECT SUM(annual_gain_vs_blast) AS annual_gain_vs_blast
FROM workspace.nbo_demo.promo_portfolio;

-- Dataset: spend_vs_margin_trend  (line chart: x = month_end, y = usd, color = measure)
SELECT month_end, 'Discount spend' AS measure, MEASURE(discount_spend) AS usd
FROM workspace.nbo_demo.metrics_promotions
GROUP BY month_end
UNION ALL
SELECT month_end, 'Incremental margin' AS measure, MEASURE(incremental_margin) AS usd
FROM workspace.nbo_demo.metrics_promotions
GROUP BY month_end;

-- =====================================================================
-- Page 2 · "Where is the waste?"
-- =====================================================================

-- Dataset: redemption_vs_lift  (grouped bar: x = promotion, y = rate, color = measure)
SELECT promotion, 'Redemption rate' AS measure, MEASURE(redemption_rate) AS rate
FROM workspace.nbo_demo.metrics_promotions
WHERE send_policy = 'All eligible (Apr-Sep)'
GROUP BY promotion
UNION ALL
SELECT promotion, 'Measured lift' AS measure, MEASURE(measured_lift) AS rate
FROM workspace.nbo_demo.metrics_promotions
WHERE send_policy = 'All eligible (Apr-Sep)'
GROUP BY promotion;

-- Dataset: margin_by_region
SELECT region, promotion, MEASURE(incremental_margin) AS incremental_margin
FROM workspace.nbo_demo.metrics_promotions
WHERE send_policy = 'All eligible (Apr-Sep)'
GROUP BY region, promotion;

-- Dataset: tier_backtest
SELECT p.short_name AS promotion, b.tier, b.measured_uplift, b.treatment_sends, b.holdout_sends
FROM workspace.nbo_demo.tier_backtest b
JOIN workspace.nbo_demo.promotions p USING (promotion_id)
WHERE b.holdout_sends >= 30;

-- Dataset: portfolio
SELECT opportunity_rank, short_name AS promotion, eligible_members, persuadable_members,
       redemption_rate_apr_sep, measured_uplift_apr_sep,
       blast_net_margin_per_send, targeted_net_margin_per_send, annual_opportunity_targeted, status
FROM workspace.nbo_demo.promo_portfolio
ORDER BY opportunity_rank;
