# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Stream in-store check-ins through the decision path
# MAGIC
# MAGIC While a shopper is in the store, the system picks the promotion most likely to get that person
# MAGIC to add to their basket and sends it to them right then.
# MAGIC
# MAGIC This notebook reads `instore_events` as a stream, joins each micro-batch to the shoppers' uplift
# MAGIC scores in `member_offer_scores`, runs the shared decision code (`app/nbo_decision.py`: live
# MAGIC rules, tiers, arbitration, 10% holdout), and appends one decision per check-in to
# MAGIC `offer_decisions`. The job uses `availableNow` so it drains the live day and stops; point the
# MAGIC same code at a Zerobus- or Kafka-fed table and remove the trigger to run it continuously.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nbo_demo")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
fq = f"{catalog}.{schema}"

import os
import sys

import pandas as pd

sys.path.insert(0, os.getcwd())
import nbo_lib  # noqa: E402  (also puts app/ on the path for nbo_decision)
import nbo_decision as nd  # noqa: E402

checkpoint = f"/Volumes/{catalog}/{schema}/checkpoints/offer_decisions"
spark.sql(f"CREATE VOLUME IF NOT EXISTS {fq}.checkpoints")
spark.sql(f"DROP TABLE IF EXISTS {fq}.offer_decisions")
dbutils.fs.rm(checkpoint, True)

# Scores and opt-in are the "online" side of the join, loaded once per run
scores = spark.table(f"{fq}.member_offer_scores").select(
    "member_id", "promotion_id", "eligible", "p_without_offer", "p_with_offer", "uplift",
    "expected_net_margin").toPandas()
opt_in = spark.table(f"{fq}.member_features").select("member_id", "marketing_opt_in").toPandas()

# COMMAND ----------

def decide_batch(batch_df, batch_id):
    events = batch_df.toPandas()
    if events.empty:
        return
    events["event_ts"] = pd.to_datetime(events.event_ts)
    decisions = nd.decide(nd.offer_candidates(events, scores, opt_in))
    decisions["batch_id"] = batch_id
    decisions["decided_at"] = pd.Timestamp.utcnow().tz_localize(None)
    (spark.createDataFrame(decisions.astype({"promotion_id": "string", "offer_message": "string",
                                             "channel": "string"}))
     .write.mode("append").saveAsTable(f"{fq}.offer_decisions"))


query = (spark.readStream
         .option("maxFilesPerTrigger", 1)
         .table(f"{fq}.instore_events")
         .writeStream
         .foreachBatch(decide_batch)
         .option("checkpointLocation", checkpoint)
         .trigger(availableNow=True)
         .start())
query.awaitTermination()

# COMMAND ----------

display(spark.sql(f"""
SELECT daypart, decision, COUNT(*) AS check_ins
FROM {fq}.offer_decisions
GROUP BY daypart, decision
ORDER BY daypart, decision
"""))
