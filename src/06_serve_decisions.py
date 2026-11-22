# Databricks notebook source
# MAGIC %md
# MAGIC # 06 · Real-time decision endpoint
# MAGIC
# MAGIC While a shopper is in the store, the system picks the promotion most likely to get that person
# MAGIC to add to their basket and sends it to them right then.
# MAGIC
# MAGIC 1. **Online features.** `member_features` becomes a Unity Catalog feature table (primary key
# MAGIC    `member_id`, change data feed on) and is published to a Lakebase-backed online store with
# MAGIC    `CONTINUOUS` sync, so every update the pipeline writes is readable by key in milliseconds.
# MAGIC 2. **Decision model.** `nbo_decision_service` wraps the uplift learners and the live rules
# MAGIC    (`app/nbo_decision.py`) in one pyfunc, logged with a `FeatureLookup`, so the endpoint fetches
# MAGIC    the shopper's features itself. The caller sends only the check-in.
# MAGIC 3. **Endpoint.** `nbo-decision` serves it, with an AI Gateway inference table that logs every
# MAGIC    request and response to Unity Catalog for the dashboard and for retraining.
# MAGIC 4. **App access.** The app's service principal gets `CAN_QUERY` on the endpoint.

# COMMAND ----------

# MAGIC %pip install -q "mlflow>=2.22.0" "databricks-feature-engineering>=0.16.0" "databricks-sdk>=0.50" scikit-learn==1.5.2

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nbo_demo")
dbutils.widgets.text("endpoint_name", "nbo-decision")
dbutils.widgets.text("app_name", "nbo-decision-engine")
dbutils.widgets.text("online_store", "nbo-online-store")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
endpoint_name = dbutils.widgets.get("endpoint_name")
app_name = dbutils.widgets.get("app_name")
online_store_name = dbutils.widgets.get("online_store")
fq = f"{catalog}.{schema}"
model_name = f"{fq}.nbo_decision_service"

import os
import sys

sys.path.insert(0, os.getcwd())
import nbo_lib  # noqa: E402  (puts app/ on the path)
import nbo_decision as nd  # noqa: E402

APP_DIR = os.path.abspath(os.path.join(os.getcwd(), "..", "app"))
sys.path.insert(0, APP_DIR)

# COMMAND ----------

# MAGIC %md ## 1 · Feature table and online store

# COMMAND ----------

from databricks.feature_engineering import FeatureEngineeringClient, FeatureLookup

fe = FeatureEngineeringClient(model_registry_uri="databricks-uc")
features_table = f"{fq}.member_features"

spark.sql(f"ALTER TABLE {features_table} ALTER COLUMN member_id SET NOT NULL")
try:
    spark.sql(f"ALTER TABLE {features_table} ADD CONSTRAINT member_features_pk PRIMARY KEY (member_id)")
except Exception as e:
    if "already exists" not in str(e).lower():
        raise
spark.sql(f"ALTER TABLE {features_table} SET TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')")

online_store = fe.get_online_store(name=online_store_name)
if online_store is None:
    fe.create_online_store(name=online_store_name, capacity="CU_1")
    import time

    for _ in range(40):
        online_store = fe.get_online_store(name=online_store_name)
        if online_store is not None and str(getattr(online_store, "state", "AVAILABLE")).endswith("AVAILABLE"):
            break
        time.sleep(15)

try:
    fe.publish_table(
        online_store=online_store,
        source_table_name=features_table,
        online_table_name=f"{features_table}_online",
        publish_mode="CONTINUOUS",
    )
    print(f"Published {features_table} to {online_store_name} (CONTINUOUS)")
except Exception as e:
    # On a rerun the build job recreates member_features; delete the online table in Catalog Explorer
    # and rerun this notebook if the existing publish is no longer syncing.
    print(f"Publish skipped: {str(e).splitlines()[0]}")

# COMMAND ----------

# MAGIC %md ## 2 · Log and register the decision model with feature lookups

# COMMAND ----------

import mlflow
import pandas as pd
from mlflow.tracking import MlflowClient

from serving_model import RESPONSE_COLS, NBODecisionService

mlflow.set_registry_uri("databricks-uc")
user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/nbo-demo-decision-service")

# The request is only the check-in: member_id, store_id, event_ts (+ optional first_scan,
# days_since_prev_visit). Shopper features come from member_features by member_id and store inventory
# from stores by store_id, both looked up by the endpoint.
stores_table = f"{fq}.stores"
spark.sql(f"ALTER TABLE {stores_table} ALTER COLUMN store_id SET NOT NULL")
try:
    spark.sql(f"ALTER TABLE {stores_table} ADD CONSTRAINT stores_pk PRIMARY KEY (store_id)")
except Exception as e:
    if "already exists" not in str(e).lower():
        raise
spark.sql(f"ALTER TABLE {stores_table} SET TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')")
try:
    fe.publish_table(online_store=online_store, source_table_name=stores_table,
                     online_table_name=f"{stores_table}_online", publish_mode="CONTINUOUS")
except Exception as e:
    print(f"Publish skipped for stores: {str(e).splitlines()[0]}")

request_cols = nd.CHECKIN_FIELDS
events = spark.table(f"{fq}.instore_events").select(*request_cols)
lookup_features = nd.MODEL_FEATURES + ["marketing_opt_in", "days_since_last_visit"]
training_set = fe.create_training_set(
    df=events,
    feature_lookups=[
        FeatureLookup(table_name=features_table, lookup_key="member_id", feature_names=lookup_features),
        FeatureLookup(table_name=stores_table, lookup_key="store_id",
                      feature_names=["has_fresh_bakery", "region", "city"]),
    ],
    label=None,
)

learners = f"/Volumes/{catalog}/{schema}/artifacts/uplift_learners.pkl"
example = training_set.load_df().limit(5).toPandas()
service = NBODecisionService()


class _Ctx:
    artifacts = {"learners": learners}


service.load_context(_Ctx())
example_out = service.predict(None, example)
display(example_out)

with mlflow.start_run(run_name="nbo-decision-service"):
    fe.log_model(
        model=service,
        artifact_path="model",
        flavor=mlflow.pyfunc,
        training_set=training_set,
        registered_model_name=model_name,
        artifacts={"learners": learners},
        code_paths=[os.path.join(APP_DIR, "nbo_decision.py"), os.path.join(APP_DIR, "serving_model.py")],
        pip_requirements=["scikit-learn==1.5.2", "pandas", "numpy"],
    )

client = MlflowClient(registry_uri="databricks-uc")
version = max(client.search_model_versions(f"name='{model_name}'"), key=lambda v: int(v.version)).version
client.set_registered_model_alias(model_name, "prod", version)
print(f"{model_name} v{version} -> @prod")

# COMMAND ----------

# MAGIC %md ## 3 · Serving endpoint with an inference table

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import (
    AiGatewayConfig,
    AiGatewayInferenceTableConfig,
    EndpointCoreConfigInput,
    ServedEntityInput,
)

w = WorkspaceClient()
entity = ServedEntityInput(entity_name=model_name, entity_version=str(version), workload_size="Small",
                           scale_to_zero_enabled=False)  # keep it warm for a live demo; turn on to save cost
existing = {e.name for e in w.serving_endpoints.list()}
if endpoint_name in existing:
    w.serving_endpoints.update_config_and_wait(name=endpoint_name, served_entities=[entity])
else:
    w.serving_endpoints.create_and_wait(
        name=endpoint_name,
        config=EndpointCoreConfigInput(served_entities=[entity]),
        ai_gateway=AiGatewayConfig(inference_table_config=AiGatewayInferenceTableConfig(
            catalog_name=catalog, schema_name=schema, table_name_prefix="nbo_decision", enabled=True)),
    )
print(f"Endpoint {endpoint_name} ready. Inference table: {fq}.nbo_decision_payload")

# COMMAND ----------

# MAGIC %md ## 4 · Let the app call it, then send one check-in

# COMMAND ----------

from databricks.sdk.service.serving import ServingEndpointAccessControlRequest, ServingEndpointPermissionLevel

try:
    sp = w.apps.get(app_name).service_principal_client_id
    ep_id = w.serving_endpoints.get(endpoint_name).id
    w.serving_endpoints.update_permissions(ep_id, access_control_list=[ServingEndpointAccessControlRequest(
        service_principal_name=sp, permission_level=ServingEndpointPermissionLevel.CAN_QUERY)])
    print(f"Granted CAN_QUERY on {endpoint_name} to app {app_name}")
except Exception as e:
    print(f"Grant the app CAN_QUERY on {endpoint_name} manually: {str(e).splitlines()[0]}")

import time

record = example[request_cols].head(1).astype({"event_ts": "string"}).to_dict("records")
# The minimum a caller needs to send:
#   {"dataframe_records": [{"member_id": 7110022051, "store_id": 1074, "event_ts": "2026-09-30 06:51:00",
#                           "first_scan": "", "days_since_prev_visit": -1}]}
t0 = time.perf_counter()
resp = w.serving_endpoints.query(name=endpoint_name, dataframe_records=record)
print(f"Round trip {1000 * (time.perf_counter() - t0):.0f} ms")
print(resp.predictions)
