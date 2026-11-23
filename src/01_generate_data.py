# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Generate synthetic in-store data
# MAGIC
# MAGIC Simulates a fictional convenience retailer's stores and loyalty shoppers from October 2025 to
# MAGIC September 2026 and writes the raw (bronze) tables: stores, loyalty members, POS baskets, the
# MAGIC promotion catalog, every in-store offer served in 2026 with its 10% holdout, and
# MAGIC `instore_events`: the check-in stream for the live day (2026-09-30) that the real-time decision
# MAGIC path scores.
# MAGIC
# MAGIC History built in: Jan-Mar in-store offers ran as a curated pilot. From 2026-04-01 a static rules
# MAGIC engine showed every eligible offer at every check-in. Discount spend tripled and incremental
# MAGIC margin went negative, because most shoppers who got an offer already buy the promoted item.
# MAGIC That holdout data is what the uplift model learns from.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nbo_demo")
dbutils.widgets.text("members", "25000")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
members = int(dbutils.widgets.get("members"))
fq = f"{catalog}.{schema}"
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {fq}")

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.getcwd())
import nbo_lib  # noqa: E402

raw = nbo_lib.simulate(members=members)
raw["instore_events"] = nbo_lib.instore_events(raw)
for name, df in raw.items():
    print(f"{name}: {len(df):,} rows")

# COMMAND ----------

for name, df in raw.items():
    nbo_lib.save_delta(spark, df, f"{fq}.{name}", nbo_lib.RAW_DATE_COLS.get(name, ()))
