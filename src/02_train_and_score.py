# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Features, uplift model, scores, and gold tables
# MAGIC
# MAGIC - `member_features` (silver): one row per member. Visit mix, category rates, and recency
# MAGIC   computed from `pos_baskets`.
# MAGIC - Uplift model: for each promotion, one response model trained on members who got the offer
# MAGIC   and one on the holdout. Uplift is the difference. Logged to MLflow and registered in Unity
# MAGIC   Catalog as `nbo_uplift_model`.
# MAGIC - `member_offer_scores`: every member × promotion with likelihood to buy with and without the
# MAGIC   offer, lift, expected net margin, tier (Persuadable, Sure Thing, Lost Cause, Low ROI), and the
# MAGIC   next best offer.
# MAGIC - Gold tables read by the decision path, app, dashboard, and Genie: `promo_monthly`,
# MAGIC   `promo_portfolio`, `audience_tiers`, `tier_backtest`, `member_profile`, `featured_events`.
# MAGIC - `member_offer_scores` is the table the real-time decision path looks up by `member_id`. In
# MAGIC   production it is synced to an online table (Lakebase) for millisecond reads.

# COMMAND ----------

# MAGIC %pip install -q scikit-learn==1.5.2

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nbo_demo")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
fq = f"{catalog}.{schema}"

# COMMAND ----------

import os
import sys

import pandas as pd

sys.path.insert(0, os.getcwd())
import nbo_lib  # noqa: E402

raw = {name: spark.table(f"{fq}.{name}").toPandas()
       for name in ["loyalty_members", "promotions", "offer_history", "instore_events"]}
raw["instore_events"]["event_ts"] = pd.to_datetime(raw["instore_events"]["event_ts"])
for name, cols in nbo_lib.RAW_DATE_COLS.items():
    for c in cols:
        raw[name][c] = pd.to_datetime(raw[name][c])
# Only the columns member_features reads, to keep the driver-side copy small
basket_cols = ["member_id", "basket_ts", "daypart", "basket_value"] + [f"has_{c}" for c in nbo_lib.CATEGORIES]
baskets = spark.table(f"{fq}.pos_baskets").select(*basket_cols).toPandas()
baskets["basket_ts"] = pd.to_datetime(baskets.basket_ts)

# Train on behaviour before the April rules change; score on the full 12 months to 2026-09-30
train_f, score_f = nbo_lib.feature_windows(baskets, raw["loyalty_members"])
del baskets
print(f"Features: {len(score_f):,} members")

# COMMAND ----------

import mlflow
import mlflow.pyfunc
from mlflow.models import infer_signature


class UpliftModel(mlflow.pyfunc.PythonModel):
    """Scores members against every promotion: likelihood to buy with and without the offer."""

    def __init__(self, models, features):
        self.models = models
        self.features = features

    def predict(self, context, model_input):
        X = model_input[self.features]
        out = {}
        for pid, m in self.models.items():
            p_t, p_c = nbo_lib.predict_response(m, X)
            out[f"{pid}_p_with_offer"] = p_t
            out[f"{pid}_p_without_offer"] = p_c
            out[f"{pid}_uplift"] = p_t - p_c
        return pd.DataFrame(out)


user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/nbo-demo-uplift")
mlflow.set_registry_uri("databricks-uc")

with mlflow.start_run(run_name="t-learner-uplift") as run:
    models = nbo_lib.train_uplift(raw["offer_history"], train_f)
    estimator = next(iter(models.values()))["treated"]
    mlflow.log_params({"learner": "two-model (T-learner)", "estimator": type(estimator).__name__,
                       "max_depth": estimator.max_depth, "max_iter": estimator.max_iter,
                       "train_window": f"{nbo_lib.HISTORY_START:%Y-%m-%d}..{nbo_lib.PRE_END:%Y-%m-%d}",
                       "features": len(nbo_lib.MODEL_FEATURES)})
    for pid, m in models.items():
        mlflow.log_metrics({f"{pid}_treated_rows": m["treated_rows"], f"{pid}_holdout_rows": m["control_rows"]})

    wrapped = UpliftModel(models, nbo_lib.MODEL_FEATURES)
    example = score_f[nbo_lib.MODEL_FEATURES].head(20)
    signature = infer_signature(example, wrapped.predict(None, example))
    try:
        mlflow.pyfunc.log_model(artifact_path="uplift_model", python_model=wrapped, signature=signature,
                                input_example=example, pip_requirements=["scikit-learn==1.5.2", "pandas"],
                                registered_model_name=f"{fq}.nbo_uplift_model")
        print(f"Registered {fq}.nbo_uplift_model")
    except Exception as e:
        print(f"Model logged without registration: {str(e).splitlines()[0]}")

    scores = nbo_lib.score_members(models, score_f)
    gold = nbo_lib.build_gold(raw, scores, score_f)

    bt = gold["tier_backtest"]
    for row in bt.itertuples():
        mlflow.log_metric(f"{row.promotion_id}_{row.tier.replace(' ', '_')}_measured_uplift", row.measured_uplift)

# COMMAND ----------

# Save the fitted learners for the real-time decision endpoint (notebook 06)
import pickle

spark.sql(f"CREATE VOLUME IF NOT EXISTS {fq}.artifacts")
with open(f"/Volumes/{catalog}/{schema}/artifacts/uplift_learners.pkl", "wb") as fh:
    pickle.dump({pid: {"treated": m["treated"], "control": m["control"]} for pid, m in models.items()}, fh)

# COMMAND ----------

gold_date_cols = {"member_profile": ["enrolled_date"], "promo_monthly": ["month_end"]}
for name, pdf in {"member_features": score_f, **gold}.items():
    nbo_lib.save_delta(spark, pdf, f"{fq}.{name}", gold_date_cols.get(name, ()))

display(spark.table(f"{fq}.promo_portfolio"))
