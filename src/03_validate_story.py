# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Validate the story
# MAGIC
# MAGIC Runs before access rules are applied, so it sees every region. Checks that the generated data
# MAGIC tells the demo story and prints the numbers to copy into the demo script.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nbo_demo")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
fq = f"{catalog}.{schema}"

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.getcwd())
import nbo_lib  # noqa: E402

monthly = spark.table(f"{fq}.promo_monthly").toPandas()
portfolio = spark.table(f"{fq}.promo_portfolio").toPandas().sort_values("opportunity_rank")
backtest = spark.table(f"{fq}.tier_backtest").toPandas()

nbo_lib.story_checks(nbo_lib.story_numbers(monthly, portfolio, backtest))

# COMMAND ----------

display(spark.sql(f"""
SELECT month_end,
       ROUND(SUM(discount_cost)) AS discount_spend,
       ROUND(SUM(incremental_margin)) AS incremental_margin
FROM {fq}.promo_monthly
GROUP BY month_end
ORDER BY month_end
"""))

# COMMAND ----------

display(spark.sql(f"""
SELECT f.display, s.promotion_id, s.tier, ROUND(s.p_without_offer, 2) AS p_without_offer,
       ROUND(s.p_with_offer, 2) AS p_with_offer, s.is_next_best_offer, s.reason
FROM {fq}.featured_members f
JOIN {fq}.member_offer_scores s USING (member_id)
WHERE s.eligible
ORDER BY f.display, s.expected_net_margin DESC
"""))
