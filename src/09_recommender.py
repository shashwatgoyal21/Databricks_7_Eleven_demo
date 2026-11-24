# Databricks notebook source
# MAGIC %md
# MAGIC # 09 · Recommender: the trained model behind the app's Recommendations tab
# MAGIC
# MAGIC 1. Trains `nbo_recommender`, a random forest that predicts net margin per offer for each promotion x region
# MAGIC    under each targeting policy, from the stored history (`promo_monthly`) and the live day (`offer_performance`).
# MAGIC 2. Registers it in Unity Catalog.
# MAGIC 3. Scores candidate changes (pause, scale, switch to model targeting, move volume between regions) and writes
# MAGIC    the top ones to `agent_proposals`. Proposals from earlier runs that nobody decided are marked superseded.
# MAGIC 4. Creates the metric view `nbo_offer_metrics`, one definition of the offer measures for the app, the AI/BI
# MAGIC    dashboard and Genie.
# MAGIC
# MAGIC Nothing in the app's recommendations is typed by hand: titles, evidence and impact come from this run.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nbo_demo")
dbutils.widgets.text("app_name", "nbo-decision-engine")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
app_name = dbutils.widgets.get("app_name")
fq = f"{catalog}.{schema}"

import os
import sys

import pandas as pd

sys.path.insert(0, os.getcwd())
import nbo_lib  # noqa: E402

t = {n: spark.table(f"{fq}.{n}").toPandas()
     for n in ["promo_monthly", "offer_performance", "promotions", "promo_portfolio", "stores"]}
assumptions = {r.key: float(r.value) for r in spark.table(f"{fq}.finance_assumptions").collect()}
print(assumptions)

# COMMAND ----------

# MAGIC %md ## Train and register

# COMMAND ----------

import mlflow
import mlflow.sklearn
from mlflow.models import infer_signature

frame = nbo_lib.recommender_training_frame(t["promo_monthly"], t["offer_performance"], t["promotions"],
                                           t["promo_portfolio"])
user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/nbo-demo-recommender")
mlflow.set_registry_uri("databricks-uc")

version = "1"
with mlflow.start_run(run_name="nbo-recommender") as run:
    model = nbo_lib.train_recommender(frame)
    mlflow.log_params({"estimator": "RandomForestRegressor", "n_estimators": model.n_estimators,
                       "features": ",".join(nbo_lib.RECOMMENDER_FEATURES), "training_rows": len(frame)})
    mlflow.log_metric("training_r2", float(model.score(frame[nbo_lib.RECOMMENDER_FEATURES], frame.net_per_offer)))
    X = frame[nbo_lib.RECOMMENDER_FEATURES].head(20)
    try:
        info = mlflow.sklearn.log_model(model, artifact_path="recommender",
                                        signature=infer_signature(X, model.predict(X)), input_example=X,
                                        registered_model_name=f"{fq}.{nbo_lib.RECOMMENDER_NAME}")
        version = str(info.registered_model_version or "1")
        print(f"Registered {fq}.{nbo_lib.RECOMMENDER_NAME} version {version}")
    except Exception as e:
        print(f"Model logged without registration: {str(e).splitlines()[0]}")

# COMMAND ----------

# MAGIC %md ## Score candidate changes and store the proposals

# COMMAND ----------

proposals = nbo_lib.recommend(model, frame, t["offer_performance"], t["promotions"], t["promo_portfolio"],
                              assumptions, pilot_stores=len(t["stores"]),
                              live_days=max(t["offer_performance"].decision_date.nunique(), 1),
                              model_version=version)
display(proposals)

new_cols = {"region": "STRING", "action": "STRING", "expected_annual_profit_usd": "DOUBLE",
            "expected_annual_sales_usd": "DOUBLE", "confidence": "STRING", "evidence": "STRING",
            "rollout": "STRING", "model_name": "STRING", "model_version": "STRING", "scored_at": "TIMESTAMP",
            "reject_reason": "STRING"}
have = {c.name for c in spark.table(f"{fq}.agent_proposals").schema}
missing = [f"{c} {typ}" for c, typ in new_cols.items() if c not in have]
if missing:
    spark.sql(f"ALTER TABLE {fq}.agent_proposals ADD COLUMNS ({', '.join(missing)})")

spark.sql(f"UPDATE {fq}.agent_proposals SET status = 'superseded' WHERE status = 'proposed'")
if len(proposals):
    types = {"expected_monthly_impact_usd": "DOUBLE", "expected_annual_profit_usd": "DOUBLE",
             "expected_annual_sales_usd": "DOUBLE", "proposal_date": "DATE", "decided_at": "TIMESTAMP",
             "created_at": "TIMESTAMP", "scored_at": "TIMESTAMP"}
    sdf = spark.createDataFrame(proposals.astype(object).where(proposals.notna(), None),
                                ", ".join(f"{c} {'DOUBLE' if types.get(c) == 'DOUBLE' else 'STRING'}"
                                          for c in nbo_lib.PROPOSAL_COLUMNS))
    (sdf.selectExpr(*[f"CAST({c} AS {types.get(c, 'STRING')}) AS {c}" for c in nbo_lib.PROPOSAL_COLUMNS])
     .write.mode("append").saveAsTable(f"{fq}.agent_proposals"))
print(f"{len(proposals)} proposals written")

# COMMAND ----------

# MAGIC %md ## Metric view: one definition of the offer measures

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {fq}.nbo_offer_metrics
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: "In-store offer engine measures. Promotion, region and daypart level only, no shoppers. Lift is measured against the 10% control group that gets no offer."
source: {fq}.offer_performance
dimensions:
  - name: decision_date
    expr: decision_date
  - name: promotion_id
    expr: promotion_id
  - name: region
    expr: region
  - name: daypart
    expr: daypart
measures:
  - name: offers_served
    expr: SUM(offers_served)
  - name: acceptance_rate
    expr: SUM(accepted) / NULLIF(SUM(delivered), 0)
  - name: redemption_rate
    expr: SUM(redeemed) / NULLIF(SUM(offers_served), 0)
  - name: lift_vs_control
    expr: SUM(redeemed) / NULLIF(SUM(offers_served), 0) - SUM(holdout_redeemed) / NULLIF(SUM(holdout_checkins), 0)
  - name: incremental_margin
    expr: SUM(incremental_margin)
  - name: discount_cost
    expr: SUM(discount_cost)
  - name: compute_cost
    expr: SUM(compute_cost_usd)
  - name: net_return
    expr: SUM(net_return)
  - name: return_on_spend
    expr: SUM(net_return) / NULLIF(SUM(discount_cost) + SUM(compute_cost_usd), 0)
$$""")
print(f"Metric view {fq}.nbo_offer_metrics")

# COMMAND ----------

# MAGIC %md ## The app can read the model and write decisions

# COMMAND ----------

try:
    from databricks.sdk import WorkspaceClient
    sp = WorkspaceClient().apps.get(app_name).service_principal_client_id
    spark.sql(f"GRANT SELECT, MODIFY ON TABLE {fq}.agent_proposals TO `{sp}`")
    spark.sql(f"GRANT SELECT ON TABLE {fq}.nbo_offer_metrics TO `{sp}`")
except Exception as e:
    print(f"Grants skipped: {str(e).splitlines()[0]}")
