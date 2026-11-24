# Databricks notebook source
# MAGIC %md
# MAGIC # 07 · Offer ledger: store what happened after every decision
# MAGIC
# MAGIC Every measure the app and the agent show is computed from stored history in Unity Catalog:
# MAGIC
# MAGIC | Table | One row per | What it holds |
# MAGIC |---|---|---|
# MAGIC | `offer_outcomes` | check-in | decision, delivered, accepted, redeemed, discount paid, compute cost |
# MAGIC | `offer_performance` | day x promotion x region x daypart | acceptance rate, redemption rate, measured lift vs holdout, incremental margin, net return, return on spend |
# MAGIC | `compute_cost` | run of this job | serving cost per decision, measured from `system.billing` when readable |
# MAGIC | `promotion_changes` | change to the offer catalog | who changed which promotion, from what to what, and why |
# MAGIC | `agent_proposals` | agent recommendation | the proposal, expected monthly impact, status (proposed, approved, rejected) |
# MAGIC | `agent_activity` | question or action | what was asked or done, who did it, what the agent routed to |
# MAGIC
# MAGIC The demo draws delivery, acceptance and redemption from the model's own probabilities. In production
# MAGIC the same columns come from the push provider's delivery receipts, app taps and the POS redemption feed.
# MAGIC No table here is shown per shopper in the app: it reads rates and money only.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nbo_demo")
dbutils.widgets.text("endpoint_name", "nbo-decision")
dbutils.widgets.text("app_name", "nbo-decision-engine")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
endpoint = dbutils.widgets.get("endpoint_name")
app_name = dbutils.widgets.get("app_name")
fq = f"{catalog}.{schema}"

import os
import sys

import pandas as pd

sys.path.insert(0, os.getcwd())
import nbo_lib  # noqa: E402

# COMMAND ----------

# MAGIC %md ## Compute cost per decision, from system.billing when readable

# COMMAND ----------

cost_per_decision, cost_source = nbo_lib.COMPUTE_COST_PER_DECISION, "estimate (system.billing not readable)"
try:
    spend = spark.sql(f"""
        SELECT SUM(u.usage_quantity * p.pricing.default) AS usd
        FROM system.billing.usage u
        JOIN system.billing.list_prices p
          ON u.sku_name = p.sku_name AND u.usage_start_time >= p.price_start_time
         AND (p.price_end_time IS NULL OR u.usage_end_time <= p.price_end_time)
        WHERE u.usage_metadata.endpoint_name = '{endpoint}' AND u.usage_date >= current_date() - 30
          AND u.billing_origin_product = 'MODEL_SERVING'
    """).first().usd
    # Denominator = every request the endpoint served in the same 30 days. The inference table logs all of
    # them; live_decision_log only holds calls made from the app, which undercounts and inflates the rate.
    try:
        calls = spark.sql(f"SELECT COUNT(*) AS n FROM {fq}.nbo_decision_payload "
                          f"WHERE request_time >= current_date() - 30").first().n
    except Exception:
        calls = spark.sql(f"SELECT COUNT(*) AS n FROM {fq}.live_decision_log "
                          f"WHERE logged_at >= current_date() - 30").first().n
    if spend and calls:
        cost_per_decision, cost_source = float(spend) / calls, f"system.billing, last 30 days, {calls:,} calls"
except Exception as e:
    print(f"Billing lookup skipped: {str(e).splitlines()[0]}")
print(f"Compute cost per decision: ${cost_per_decision:.6f} ({cost_source})")

spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq}.compute_cost (
  measured_at TIMESTAMP, endpoint_name STRING, cost_per_decision_usd DOUBLE, source STRING)
  COMMENT 'Serving cost per offer decision, one row per ledger run.'""")
spark.sql(f"INSERT INTO {fq}.compute_cost VALUES (current_timestamp(), '{endpoint}', {cost_per_decision}, "
          f"'{cost_source}')")

# COMMAND ----------

# MAGIC %md ## Outcomes and performance

# COMMAND ----------

decisions = spark.table(f"{fq}.offer_decisions").toPandas()
promotions = spark.table(f"{fq}.promotions").toPandas()
outcomes = nbo_lib.offer_outcomes(decisions, promotions, cost_per_decision)
performance = nbo_lib.offer_performance(outcomes, promotions)
nbo_lib.save_delta(spark, outcomes, f"{fq}.offer_outcomes", ["decision_date"])
nbo_lib.save_delta(spark, performance, f"{fq}.offer_performance", ["decision_date"])

comments = {
    "offer_outcomes": "One row per in-store check-in: the offer decision and what happened after it "
                      "(delivered, accepted, redeemed, discount paid, compute cost).",
    "offer_performance": "Daily measures by promotion, region and daypart, computed from offer_outcomes: "
                         "acceptance rate, redemption rate, lift vs the 10% holdout, incremental margin, "
                         "net return after discounts and compute, return on spend.",
}
for t, c in comments.items():
    spark.sql(f"COMMENT ON TABLE {fq}.{t} IS '{c}'")

# COMMAND ----------

# MAGIC %md ## Catalog changes, agent proposals and agent activity

# COMMAND ----------

spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq}.promotion_changes (
  change_id STRING, promotion_id STRING, change_type STRING, field STRING, old_value STRING, new_value STRING,
  reason STRING, source STRING, changed_by STRING, changed_at TIMESTAMP)
  COMMENT 'Every change to the offer catalog: created, edited, scaled, paused, retired. Source is user or agent.'""")
if spark.table(f"{fq}.promotion_changes").limit(1).count() == 0:
    spark.sql(f"""INSERT INTO {fq}.promotion_changes
      SELECT uuid(), promotion_id, 'created', NULL, NULL, promotion_name, 'Initial catalog', 'build job',
             current_user(), current_timestamp() FROM {fq}.promotions""")

spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq}.agent_proposals (
  proposal_id STRING, proposal_date DATE, promotion_id STRING, kind STRING, title STRING, rationale STRING,
  expected_monthly_impact_usd DOUBLE, status STRING, decided_by STRING, decided_at TIMESTAMP,
  created_at TIMESTAMP)
  COMMENT 'Recommendations the offer agent made, and whether a person approved or rejected them.'""")

spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq}.agent_activity (
  activity_id STRING, activity_type STRING, content STRING, routed_to STRING, user_name STRING,
  created_at TIMESTAMP)
  COMMENT 'Questions asked of the offer agent and actions it took. Promotion level only, no shopper data.'""")

# COMMAND ----------

# MAGIC %md ## Finance assumptions (owned by finance, edit in Catalog Explorer or SQL)

# COMMAND ----------

import ast  # noqa: E402

# Read DEFAULTS from app/finance.py without importing it (that module needs Streamlit, not on job compute)
_src = open(os.path.join(os.getcwd(), "..", "app", "finance.py")).read()
DEFAULTS = next(ast.literal_eval(n.value) for n in ast.parse(_src).body
                if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "DEFAULTS" for t in n.targets))

spark.sql(f"""CREATE TABLE IF NOT EXISTS {fq}.finance_assumptions (
  key STRING, value DOUBLE, unit STRING, description STRING, updated_by STRING, updated_at TIMESTAMP)
  COMMENT 'Assumptions the app uses to scale pilot results to the network and compute ROIC. Edit to change.'""")
existing = {r.key for r in spark.table(f"{fq}.finance_assumptions").select("key").collect()}
new = [(k, float(v[0]), v[1], v[2]) for k, v in DEFAULTS.items() if k not in existing]
if new:
    (spark.createDataFrame(new, "key STRING, value DOUBLE, unit STRING, description STRING")
     .selectExpr("*", "current_user() AS updated_by", "current_timestamp() AS updated_at")
     .write.mode("append").saveAsTable(f"{fq}.finance_assumptions"))
display(spark.table(f"{fq}.finance_assumptions"))

# COMMAND ----------

# MAGIC %md ## Governance: same region row filter, and write access for the app

# COMMAND ----------

for t in ["offer_outcomes", "offer_performance"]:
    try:
        spark.sql(f"ALTER TABLE {fq}.{t} SET ROW FILTER {fq}.nbo_region_filter ON (region)")
    except Exception as e:
        print(f"Row filter on {t} skipped: {str(e).splitlines()[0]}")

try:
    from databricks.sdk import WorkspaceClient
    sp = WorkspaceClient().apps.get(app_name).service_principal_client_id
    for t in ["agent_proposals", "agent_activity", "promotion_changes"]:
        spark.sql(f"GRANT SELECT, MODIFY ON TABLE {fq}.{t} TO `{sp}`")
    print(f"App service principal {sp} can write agent_proposals, agent_activity and promotion_changes")
except Exception as e:
    print(f"App grants skipped: {str(e).splitlines()[0]}. Grant MODIFY on those three tables to the app's "
          f"service principal in Catalog Explorer.")

# COMMAND ----------

display(spark.sql(f"""
  SELECT promotion_id, SUM(offers_served) AS offers_served,
         ROUND(SUM(accepted) / SUM(delivered), 3) AS acceptance_rate,
         ROUND(SUM(net_return), 2) AS net_return_usd,
         ROUND(SUM(net_return) / (SUM(discount_cost) + SUM(compute_cost_usd)), 3) AS return_on_spend
  FROM {fq}.offer_performance GROUP BY promotion_id ORDER BY net_return_usd DESC"""))
