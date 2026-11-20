# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Generate synthetic loyalty data
# MAGIC
# MAGIC Simulates a fictional convenience-retail loyalty program from October 2025 to September 2026
# MAGIC and writes the raw tables: stores, loyalty members, POS baskets, the promotion catalog, and
# MAGIC every offer sent in 2026 with its 10% holdout.
# MAGIC
# MAGIC The story is built into the simulation: until March, marketers sent offers to small curated
# MAGIC segments. On 2026-04-01 every offer started going to everyone eligible. Discount spend tripled,
# MAGIC but incremental margin fell, because most new recipients already buy the promoted item. The
# MAGIC clearest case is the Coffee + Croissant bundle: about 40% of morning commuters already add a
# MAGIC pastry to most coffee visits.

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
for name, df in raw.items():
    print(f"{name}: {len(df):,} rows")

# COMMAND ----------

for name, df in raw.items():
    nbo_lib.save_delta(spark, df, f"{fq}.{name}", nbo_lib.RAW_DATE_COLS.get(name, ()))
