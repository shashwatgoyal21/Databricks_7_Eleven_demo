# Databricks notebook source
# MAGIC %md
# MAGIC # 08 · Offer agent: Genie space + Multi-Agent Supervisor
# MAGIC
# MAGIC Sets up the agent behind the app's chat button:
# MAGIC 1. A Genie space over the promotion-level tables (`offer_performance`, `promo_portfolio`, `promotions`,
# MAGIC    `promotion_changes`, `agent_proposals`, `compute_cost`).
# MAGIC 2. A Multi-Agent Supervisor (Agent Bricks) named "NBO Offer Agent" that routes questions to that space.
# MAGIC 3. Permission for the app's service principal to use both.
# MAGIC 4. The `agent_config` table the app reads to find them.
# MAGIC
# MAGIC Every step prints what it did. If a step fails, the printout says what to do in the UI instead.

# COMMAND ----------

# MAGIC %pip install -q "databricks-sdk>=0.70"
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "nbo_demo")
dbutils.widgets.text("warehouse_id", "")
dbutils.widgets.text("app_name", "nbo-decision-engine")
dbutils.widgets.text("genie_space_id", "")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
warehouse_id = dbutils.widgets.get("warehouse_id")
app_name = dbutils.widgets.get("app_name")
space_id = dbutils.widgets.get("genie_space_id").strip()
fq = f"{catalog}.{schema}"

import json
import time

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
AGENT = "NBO Offer Agent"
SPACE_TITLE = "In-Store NBO Performance"
TABLES = ["offer_performance", "promo_portfolio", "promotions", "promotion_changes", "agent_proposals",
          "compute_cost"]

try:
    sp = w.apps.get(app_name).service_principal_client_id
    print(f"App service principal: {sp}")
except Exception as e:
    sp = None
    print(f"Could not look up app {app_name}: {str(e).splitlines()[0]}")

# COMMAND ----------

# MAGIC %md ## 1. Genie space

# COMMAND ----------

if not space_id:
    try:
        for s in w.genie.list_spaces().spaces or []:
            if s.title == SPACE_TITLE:
                space_id = s.space_id
        if space_id:
            print(f"Found Genie space {space_id}")
    except Exception as e:
        print(f"Listing Genie spaces failed: {str(e).splitlines()[0]}")

if not space_id:
    try:
        serialized = json.dumps({"version": 1, "data_sources": {
            "tables": [{"identifier": f"{fq}.{t}"} for t in sorted(TABLES)]}})
        space_id = w.genie.create_space(
            warehouse_id=warehouse_id, serialized_space=serialized, title=SPACE_TITLE,
            description="Promotion-level results of the in-store offer engine: acceptance, lift vs holdout, "
                        "net return after discounts and compute. No individual shoppers.").space_id
        print(f"Created Genie space {space_id}")
    except Exception as e:
        print(f"Creating the Genie space failed: {str(e).splitlines()[0]}\n"
              f"Create it in the UI (Genie > New) with these tables: {', '.join(f'{fq}.{t}' for t in TABLES)}, "
              f"then re-run this task with the genie_space_id parameter.")

if space_id and sp:
    try:
        w.api_client.do("PATCH", f"/api/2.0/permissions/genie/{space_id}",
                        body={"access_control_list": [{"service_principal_name": sp, "permission_level": "CAN_RUN"}]})
        print("App can run the Genie space")
    except Exception as e:
        print(f"Genie permission skipped: {str(e).splitlines()[0]}. Share the space with the app in the UI.")

# COMMAND ----------

# MAGIC %md ## 2. Multi-Agent Supervisor

# COMMAND ----------

INSTRUCTIONS = """You are the offer agent for a convenience retailer's real-time in-store offer engine.
A trained model behind a serving endpoint picks one offer per in-store check-in; 10% of check-ins are held
back so every result is measured against what would have happened anyway.
Answer at promotion, region, daypart or segment level only. Never list or name individual shoppers.
Lead with the answer in one or two sentences, then the numbers. Use rates and money, not raw counts.
When asked what to change, recommend a concrete action (scale, retarget, pause, retire, change the incentive,
or a new promotion) with the expected monthly margin impact, and say it needs approval before it runs.
Net return = incremental margin minus discounts minus compute. Return on spend = net return / (discounts + compute).
"""
EXAMPLES = [
    ("Which offers lose money, and why?", ["Use offer_performance and promo_portfolio",
                                           "Rank by net return, explain with lift vs holdout and discount"]),
    ("What should we change this week to raise margin?", ["Recommend actions with expected monthly impact",
                                                          "Say each change needs approval"]),
    ("What is the acceptance rate by daypart?", ["Group offer_performance by daypart",
                                                 "acceptance_rate = sum(accepted) / sum(delivered)"]),
]

agent, endpoint = None, ""
try:
    sa = w.supervisor_agents
    agent = next((a for a in sa.list_supervisor_agents() if a.display_name == AGENT), None)
    if agent is None:
        agent = sa.create_supervisor_agent(display_name=AGENT, description="Answers questions about offer "
                                           "performance and recommends promotion changes.",
                                           instructions=INSTRUCTIONS)
        print(f"Created supervisor {agent.name}")
        if space_id:
            sa.create_tool(parent=agent.name, tool_id="nbo_performance", tool_type="genie_space",
                           description="Promotion performance: acceptance, lift vs holdout, net return, "
                                       "compute cost, catalog changes and agent proposals.",
                           genie_space={"id": space_id})
        for q, g in EXAMPLES:
            sa.create_example(parent=agent.name, question=q, guidelines=g)
    else:
        print(f"Found supervisor {agent.name}")
    endpoint = agent.endpoint_name
except Exception as e:
    print(f"Supervisor setup failed: {str(e).splitlines()[0]}\n"
          f"Create it in the UI (Agents > Supervisor Agent) named '{AGENT}' with the Genie space as its agent, "
          f"then put its endpoint name in the agent_config table (key supervisor_endpoint).")

# COMMAND ----------

if endpoint:
    print(f"Waiting for endpoint {endpoint} (usually about 10 minutes)")
    for _ in range(80):
        try:
            if str(w.serving_endpoints.get(endpoint).state.ready).endswith("READY"):
                break
        except Exception:
            pass
        time.sleep(15)
    if sp:
        try:
            from databricks.sdk.service.serving import (ServingEndpointAccessControlRequest,
                                                        ServingEndpointPermissionLevel)
            ep_id = w.serving_endpoints.get(endpoint).id
            w.serving_endpoints.update_permissions(ep_id, access_control_list=[ServingEndpointAccessControlRequest(
                service_principal_name=sp, permission_level=ServingEndpointPermissionLevel.CAN_QUERY)])
            print("App can query the supervisor")
        except Exception as e:
            print(f"Endpoint permission skipped: {str(e).splitlines()[0]}")

# COMMAND ----------

# MAGIC %md ## 3. Tell the app where the agent is

# COMMAND ----------

spark.sql(f"CREATE OR REPLACE TABLE {fq}.agent_config (key STRING, value STRING) "
          f"COMMENT 'Where the app finds the offer agent. Written by 08_agent.'")
spark.createDataFrame([("supervisor_endpoint", endpoint or ""), ("genie_space_id", space_id or "")],
                      "key STRING, value STRING").write.mode("append").saveAsTable(f"{fq}.agent_config")
if sp:
    try:
        spark.sql(f"GRANT SELECT ON TABLE {fq}.agent_config TO `{sp}`")
    except Exception as e:
        print(f"agent_config grant skipped: {str(e).splitlines()[0]}")
print(f"agent_config: supervisor_endpoint={endpoint or '(none)'}, genie_space_id={space_id or '(none)'}")
