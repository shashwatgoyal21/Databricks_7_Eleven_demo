# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Metric view, access rules, and the approvals table
# MAGIC
# MAGIC - `metrics_promotions`: the Unity Catalog metric view the dashboard and Genie both read.
# MAGIC - Row filter: regional marketing managers see only their region. `loyalty_leadership` sees everything.
# MAGIC - Column mask: member names and emails are visible only to `loyalty_pii`.
# MAGIC - `campaign_approvals`: written by the app when someone approves a campaign. Kept across reruns.
# MAGIC
# MAGIC Account groups used: `loyalty_leadership`, `marketing_texas`, `marketing_california`,
# MAGIC `marketing_florida`, `marketing_northeast`, `loyalty_pii`. Add yourself and the app's service
# MAGIC principal to `loyalty_leadership`, or you will see no rows.

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

REGION_GROUPS = {r: f"marketing_{r.lower()}" for r in nbo_lib.REGIONS}
GROUPS = ["loyalty_leadership", *REGION_GROUPS.values(), "loyalty_pii"]

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
  - name: offers_sent
    expr: SUM(sends)
  - name: holdout_members
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

# Groups may be account groups or workspace-local groups (a trial workspace often has only the
# latter), so each check accepts either.
def in_group(g):
    return f"(is_account_group_member('{g}') OR is_member('{g}'))"


region_clauses = "\n    ".join(f"OR (region = '{r}' AND {in_group(g)})" for r, g in REGION_GROUPS.items())
spark.sql(f"""
CREATE OR REPLACE FUNCTION {fq}.loyalty_region_filter(region STRING)
RETURN {in_group('loyalty_leadership')}
    {region_clauses}
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {fq}.loyalty_pii_mask(value STRING)
RETURN CASE WHEN {in_group('loyalty_pii')} THEN value ELSE '***' END
""")

for table in ["loyalty_members", "member_features", "member_profile", "member_offer_scores", "offer_history",
              "promo_monthly"]:
    spark.sql(f"ALTER TABLE {fq}.{table} SET ROW FILTER {fq}.loyalty_region_filter ON (region)")

for table in ["loyalty_members", "member_profile"]:
    for col in ["first_name", "last_name", "email"]:
        spark.sql(f"ALTER TABLE {fq}.{table} ALTER COLUMN {col} SET MASK {fq}.loyalty_pii_mask")

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.campaign_approvals (
  promotion_id STRING,
  promotion_name STRING,
  strategy STRING,
  audience_size BIGINT,
  expected_redemptions DOUBLE,
  expected_discount_cost DOUBLE,
  expected_net_margin DOUBLE,
  channel STRING,
  approved_by STRING,
  approved_at TIMESTAMP,
  status STRING
)
COMMENT 'Campaigns approved in the NBO app. An activation job would pick these up.'
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
      "campaign_approvals, and membership in loyalty_leadership. See README step 3.")
