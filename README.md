# Real-Time Next Best Offer demo: build kit

## What this is

While a shopper is in the store, the system picks the promotion most likely to get that person to add to their basket and sends it to them right then. A data and AI engineering audience also fits that use case. They care about the hard parts: streaming in-store signals, serving features with low latency, scoring models in milliseconds and governing all of it on Databricks.

The shopper shares their location with the app once. When they walk into a store, the app sends an *entered store* check-in with their loyalty ID to a Model Serving endpoint. The endpoint looks up their features from the online feature store, scores an uplift model for every promotion, applies the live rules (daypart, what is already scanned, store inventory, days since last visit), and returns one offer, or none, as a push notification and on the pin-pad. Every request is logged to an inference table for the AI/BI dashboard and for retraining. All shoppers, stores, and numbers are fictional.

## What gets built

| Object | Type | Purpose |
| --- | --- | --- |
| `stores` | Table | 120 stores across Texas, California, Florida, Northeast |
| `loyalty_members` | Table | Shoppers, region, segment, app and offer opt-ins (names and email masked) |
| `pos_baskets` | Table | ~3.3M POS baskets, Oct 2025 → Sep 2026, with category flags |
| `promotions` | Table | The five in-store promotions with discount cost and unit margin |
| `offer_history` | Table | Every in-store offer Jan–Sep 2026, with its 10% holdout and conversion |
| `instore_events` | Table | The live day's check-in stream (2026-09-30): shopper, store, trigger, daypart, first item scanned, days since last visit |
| `member_features` | Feature table | Visit mix, category rates, recency per shopper; primary key `member_id`, published to the online store |
| `nbo_uplift_model` | Registered model | Two response models per promotion (with offer, without offer) |
| `nbo_decision_service` | Registered model | Pyfunc: feature lookup + uplift scoring + live rules + arbitration + holdout, `@prod` |
| `nbo-decision` | Model Serving endpoint | Real-time decision per check-in, with an AI Gateway inference table |
| `nbo_decision_payload` | Inference table | Every request and response to the endpoint |
| `member_offer_scores` | Table | Shopper × promotion scores from the nightly batch, used by the trace view |
| `offer_decisions` | Table | One decision per check-in, written by the streaming decision job |
| `live_decision_log` | Table | Decisions made from the app |
| `promo_monthly`, `promo_portfolio`, `audience_tiers`, `tier_backtest`, `featured_events`, `member_profile` | Tables | Gold tables for the app, dashboard, and Genie |
| `metrics_promotions` | Metric view | Governed offer KPIs read by the dashboard and Genie |
| `nbo_region_filter` | Function | Row filter by region |
| `nbo_pii_mask` | Function | Names and email visible only to `nbo_pii_readers` |
| `nbo-decision-engine` | Databricks App | Live in-store view: share location, walk in, offer pushed |

Shared code: `app/nbo_decision.py` is the decision path. The endpoint, the streaming job, and the app all import it, so a rule changes in one place.

## How the 7-Eleven app calls it

The retailer's app already knows when a shopper who shared location is at a store. It makes one HTTPS call:

```bash
curl -X POST "$DATABRICKS_HOST/serving-endpoints/nbo-decision/invocations" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"dataframe_records": [{"member_id": 7110022051, "store_id": 1074, "event_ts": "2026-09-30 06:51:00",
                              "first_scan": "", "days_since_prev_visit": -1}]}'
```

Only `member_id`, `store_id`, and `event_ts` are required. `first_scan` (empty if unknown) and `days_since_prev_visit` (-1 if unknown) are optional. The endpoint looks up everything else itself.

The response carries `decision` (Offer / No offer / Holdout), `promotion_id`, `offer_message`, `push_title`, `channel`, `reason`, `expected_net_margin`, and `event_id`. The caller passes `push_title` and `offer_message` to its existing push service. In production the call comes from the app backend with a service principal token, not from the phone.

## Push delivery

The decision service does not send notifications. Delivery stays with the push stack the retailer already runs. `app/push.py` turns the decision into a request for that stack, and the demo app uses it to send real pushes:

| `NBO_PUSH_PROVIDER` | `NBO_PUSH_URL` | Also set |
| --- | --- | --- |
| `ntfy` (demo) | `https://ntfy.sh/<your topic>` | nothing |
| `webhook` | Their app backend or push gateway | nothing; receives the APNs-shaped JSON |
| `braze` | Their Braze REST endpoint | `NBO_PUSH_API_KEY` |
| `airship` | optional | `NBO_PUSH_API_KEY` |
| `onesignal` | optional | `NBO_PUSH_API_KEY`, `NBO_PUSH_APP_ID` |

Keep keys in a Databricks secret scope and map them in `app/app.yaml` with `valueFrom`. Then turn on **Send real pushes** in the app sidebar.

To get a real notification on your own phone during the demo:

1. Install the free **ntfy** app on the phone and subscribe to a topic name only you know, for example `nbo-demo-<random>`.
2. In `app/app.yaml`, set `NBO_PUSH_PROVIDER: ntfy` and `NBO_PUSH_URL: https://ntfy.sh/nbo-demo-<random>`, then redeploy.
3. In the app, turn on **Send real pushes** and click **Next shopper walks in**. Offers arrive on the phone within a second.

## Prerequisites

- A Unity Catalog workspace with serverless jobs, or a cluster on DBR 15.4 LTS ML or later.
- Model Serving and Lakebase-backed online feature stores enabled.
- A Pro or Serverless SQL warehouse for the app, dashboard, and Genie.
- Databricks Apps enabled.
- Account groups: `nbo_platform`, `nbo_region_texas`, `nbo_region_california`, `nbo_region_florida`, `nbo_region_northeast`, `nbo_pii_readers`.
- Add yourself to `nbo_platform` and `nbo_pii_readers`, or you'll see no rows and masked names after the governance step.

## Run it

```bash
databricks bundle deploy -t dev --var="catalog=workspace" --var="schema=nbo_demo" --var="warehouse_id=<warehouse id>"
databricks bundle run -t dev nbo_demo_build
databricks bundle run -t dev nbo_app
```

Deploy creates the app before the job runs, so notebook 06 can grant the app's service principal `CAN_QUERY` on the endpoint. If you change the catalog, schema, or endpoint name, also change `NBO_SCHEMA` and `NBO_ENDPOINT` in `app/app.yaml`.

| Step | Notebook | What it does |
| --- | --- | --- |
| 1 | `01_generate_data.py` | Simulates Oct 2025 → Sep 2026 and writes the raw tables, including `instore_events` (about 3 minutes) |
| 2 | `02_train_and_score.py` | Builds features, trains and registers the uplift model, saves the learners, scores shoppers, writes gold |
| 3 | `03_validate_story.py` | Checks the story numbers and prints PASS or CHECK for each |
| 5 | `05_stream_decisions.py` | Structured Streaming over `instore_events`: runs the decision path per micro-batch, writes `offer_decisions` |
| 6 | `06_serve_decisions.py` | Feature table + online store, logs `nbo_decision_service` with feature lookups, creates the `nbo-decision` endpoint with an inference table, grants the app, sends one test check-in |
| 4 | `04_governance.py` | Metric view, row filter, PII mask, `live_decision_log`, and grants |
| 7 | `07_offer_ledger.py` | Stores what happened after every decision: `offer_outcomes` (delivered, accepted, redeemed, discount, compute cost), `offer_performance` (acceptance rate, lift vs holdout, net return, return on spend), `compute_cost` (from `system.billing` when readable), and the `promotion_changes`, `agent_proposals` and `agent_activity` logs. Grants the app write access to the three logs |
| 8 | `08_agent.py` | Creates the Genie space and the "NBO Offer Agent" Multi-Agent Supervisor, gives the app access, and writes `agent_config` so the app's chat finds them (the supervisor's endpoint takes about 10 minutes) |

The job runs them in the order above. Rerunning rebuilds everything except `live_decision_log`. On a rerun, `member_features` is recreated; if the online table stops syncing, delete `member_features_online` in Catalog Explorer and rerun step 6.

For production, point check-ins at Zerobus (or Kafka) so they land in `instore_events` continuously, and drop the `availableNow` trigger in step 5.

## Tests before you deploy

```
pip install -r requirements-dev.txt
pytest
```

The tests build the demo data in pandas (about 10 seconds) and check, without a workspace:

- every SQL statement the app sends uses only tables and columns the build job creates;
- the decision model returns the documented response columns and logs with an input and output signature, as Unity Catalog requires;
- every Databricks SDK call in the notebooks and app matches the SDK (required arguments, method names);
- the bundle, the job's notebook parameters and the app config agree;
- the whole app renders with no errors and no emojis.

They run on every pull request (`.github/workflows/tests.yml`). After a deploy, `tests/test_live_workspace.py` also compiles the app's SQL against the live tables and sends one check-in to the endpoint when `DATABRICKS_HOST`, `DATABRICKS_TOKEN` and `NBO_WAREHOUSE_ID` are set.

## Finish in the UI

1. **App access.** Notebook 06 grants the app `CAN_QUERY` on the endpoint. Also add the app's service principal to `nbo_platform`, then:
   ```sql
   GRANT USE CATALOG ON CATALOG workspace TO `<app service principal>`;
   GRANT USE SCHEMA, SELECT ON SCHEMA workspace.nbo_demo TO `<app service principal>`;
   GRANT MODIFY ON TABLE workspace.nbo_demo.live_decision_log TO `<app service principal>`;
   ```
2. Click through the app once so `nbo_decision_payload` has rows, then import `dashboard/nbo_promotions.lvdash.json` (Dashboards > Create > Import), or build it by hand from `dashboard/datasets.sql` and `dashboard/layout.md`. The datasets use `workspace.nbo_demo`; edit them if you deployed elsewhere.
3. The agent. Step 8 sets up the Genie space and the supervisor. If it prints that a step failed, create that piece in the UI as the printout says, then rerun only the `agent` task with the `genie_space_id` parameter. The app's chat uses the supervisor when it's ready, the Genie space until then.
4. Test governance: sign in as a user who is only in `nbo_region_texas`. The dashboard and Genie should show Texas only, and `SELECT email FROM loyalty_members` should return `***`.

## Preview locally, no workspace

```bash
pip install pandas numpy scikit-learn==1.5.2 pyarrow fastapi uvicorn
python local_run.py                      # builds the same tables and the recommender's proposals into .local_data/
cd app && NBO_LOCAL_DATA=../.local_data uvicorn server:app --port 8000
```

Open http://localhost:8000. The app is a React front end (`frontend/`, built into `app/static/`) served by a FastAPI
back end (`app/server.py`). After changing the front end: `cd frontend && npm install && npm run build`, then commit
`app/static/`. The Databricks App runs the built files, no Node step on deploy.

## The recommender

Step 9 (`src/09_recommender.py`) trains `nbo_recommender`, a random forest that predicts net margin per offer for each
promotion x region under each targeting policy, from `promo_monthly` (history) and `offer_performance` (the engine).
It scores pause, scale, switch-to-model-targeting and move-volume changes, writes the top ones to `agent_proposals`
with their evidence, confidence and model version, and registers the model in Unity Catalog. The Recommendations tab
shows only these rows. Step 9 also creates the metric view `nbo_offer_metrics`.

## Numbers the data is built to produce

25,000 shoppers, seed 711. Step 3 prints the actual values.

| Metric | Target |
| --- | --- |
| Live-day check-ins | ~8,300 across 120 stores (~70 per store) |
| Check-ins that get an offer pushed | ~18% |
| Check-ins suppressed because no offer moves the shopper or fits the moment | ~80% |
| Measured lift, Persuadable vs Sure Thing (Coffee + Croissant holdout) | ~+22 pts vs ~0 pts |
| Static rules from Apr 1: monthly discount spend | ~$2.0K Jan–Mar → ~$8.3K Apr–Sep |
| Static rules from Apr 1: monthly incremental margin | ~+$500 → ~−$2.3K |
| Coffee + Croissant redemptions that would happen anyway under static rules | ~67% |
| Coffee + Croissant net margin per month | Static rules ~−$1.1K · model ~+$700 |
| Annual gain, model vs static rules | ~$44K on 25,000 shoppers, scaling linearly with shoppers |
