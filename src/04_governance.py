# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Metric view, access rules, and the decision log
# MAGIC
# MAGIC - `metrics_promotions`: the Unity Catalog metric view the dashboard and Genie both read.
# MAGIC - Row filter: regional data teams see only their region's rows. `nbo_platform` sees everything.
# MAGIC - Column mask: shopper names and emails are visible only to `nbo_pii_readers`.
# MAGIC - `live_decision_log`: written by the app for every decision it makes. Kept across reruns.
# MAGIC
# MAGIC Groups used (account or workspace groups): `nbo_platform`, `nbo_region_texas`, `nbo_region_california`,
# MAGIC `nbo_region_florida`, `nbo_region_northeast`, `nbo_pii_readers`. Add yourself and the app's
# MAGIC service principal to `nbo_platform`, or you will see no rows.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nbo_demo")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
fq = f"{catalog}.{schema}"

import os
import sys

sys.path.insert(0, os.getcwd())
import nbo_lib  # noqa: E402

REGION_GROUPS = {r: f"nbo_region_{r.lower()}" for r in nbo_lib.REGIONS}
GROUPS = ["nbo_platform", *REGION_GROUPS.values(), "nbo_pii_readers"]

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {fq}.metrics_promotions
WITH METRICS
LANGUAGE YAML
AS $$
version: 0.1
source: {fq}.promo_monthly
dimensions:
  - name: month_end
    expr: month_end
  - name: region
    expr: region
  - name: promotion_id
    expr: promotion_id
  - name: promotion_name
    expr: promotion_name
  - name: promotion
    expr: short_name
  - name: send_policy
    expr: send_policy
measures:
  - name: offers_served
    expr: SUM(sends)
  - name: holdout_shoppers
    expr: SUM(holdout)
  - name: redemptions
    expr: SUM(redemptions)
  - name: redemption_rate
    expr: SUM(redemptions) / NULLIF(SUM(sends), 0)
  - name: holdout_conversion_rate
    expr: SUM(holdout_conversions) / NULLIF(SUM(holdout), 0)
  - name: measured_lift
    expr: SUM(redemptions) / NULLIF(SUM(sends), 0) - SUM(holdout_conversions) / NULLIF(SUM(holdout), 0)
  - name: redemptions_that_would_happen_anyway
    expr: (SUM(holdout_conversions) / NULLIF(SUM(holdout), 0)) / NULLIF(SUM(redemptions) / NULLIF(SUM(sends), 0), 0)
  - name: discount_spend
    expr: SUM(discount_cost)
  - name: incremental_conversions
    expr: SUM(incremental_conversions)
  - name: incremental_margin
    expr: SUM(incremental_margin)
  - name: monthly_discount_spend
    expr: SUM(discount_cost) / COUNT(DISTINCT month_end)
  - name: monthly_incremental_margin
    expr: SUM(incremental_margin) / COUNT(DISTINCT month_end)
$$
""")

# COMMAND ----------

def in_group(g):
    """Account group or workspace-local group, so the demo works in workspaces without account groups."""
    return f"(is_account_group_member('{g}') OR is_member('{g}'))"


region_clauses = "\n    ".join(f"OR (region = '{r}' AND {in_group(g)})" for r, g in REGION_GROUPS.items())
spark.sql(f"""
CREATE OR REPLACE FUNCTION {fq}.nbo_region_filter(region STRING)
RETURN {in_group('nbo_platform')}
    {region_clauses}
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {fq}.nbo_pii_mask(value STRING)
RETURN CASE WHEN {in_group('nbo_pii_readers')} THEN value ELSE '***' END
""")

for table in ["loyalty_members", "member_features", "member_profile", "member_offer_scores", "offer_history",
              "promo_monthly", "instore_events", "offer_decisions"]:
    spark.sql(f"ALTER TABLE {fq}.{table} SET ROW FILTER {fq}.nbo_region_filter ON (region)")

for table in ["loyalty_members", "member_profile"]:
    for col in ["first_name", "last_name", "email"]:
        spark.sql(f"ALTER TABLE {fq}.{table} ALTER COLUMN {col} SET MASK {fq}.nbo_pii_mask")

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.live_decision_log (
  event_id BIGINT,
  store_id BIGINT,
  member_id BIGINT,
  decision STRING,
  promotion_id STRING,
  channel STRING,
  latency_ms DOUBLE,
  logged_by STRING,
  logged_at TIMESTAMP
)
COMMENT 'Every real-time offer decision made from the NBO app: one row per in-store check-in.'
""")

# COMMAND ----------

for group in GROUPS:
    try:
        spark.sql(f"GRANT USE SCHEMA, SELECT, EXECUTE ON SCHEMA {fq} TO `{group}`")
        print(f"Granted schema access to {group}")
    except Exception as e:
        print(f"Skipped grant for {group}: {str(e).splitlines()[0]}")

print("Groups also need USE CATALOG on the catalog. Grant it separately if they don't have it.")
print("The app's service principal needs: USE CATALOG, USE SCHEMA, SELECT on the schema, MODIFY on "
      "live_decision_log, and membership in nbo_platform. See README, Finish in the UI.")
