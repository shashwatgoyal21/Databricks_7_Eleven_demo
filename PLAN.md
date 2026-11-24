# Agentic Next Best Offer: Implementation Plan

> Status: **Plan complete, build not started.** All six decisions answered 2026-11-24 (§14a). This document changes no application code.
> Baseline: `chehaba/databricks-app` @ `ceb8d85` (main). Live state read 2026-11-24 on workspace `dbc-8d181d91-4a82` (the `trial` target), including the redeploy of the app from main that day.
> All shoppers, stores, numbers and the retailer brand are fictional.
> Method: every fact below is cited to a file and line, to a live read of the workspace, or marked as a default chosen in this plan (§14b).

## In plain terms

- **What the product is.** A trained model behind a Databricks Model Serving endpoint, running in the background. When a shopper checks in at a store, the endpoint picks the one promotion most likely to change what that person buys, or none, in milliseconds. The retailer's own app and push system deliver it.
- **What the app is.** A window on how the offers are doing (return on spend against the 10.1% target, offers served, acceptance, sales and profit added) plus a recommendations page. A second trained model, the recommender, proposes pause, scale, retarget and move-volume changes with expected profit. A person approves or rejects each one.
- **What is true today.** The endpoint and the app are live and show live numbers. Approving a recommendation records the approval but does not change which offers the endpoint sends. That is the main gap, and phase P2 closes it.
- **What this plan adds.** Order of work (§12), what "done" means (§15), and the numbers each check must hit (§14b).

## Decisions (answered 2026-11-24)

| # | Decision | Answer |
|---|---|---|
| D1 | Product | The trained model behind the endpoint is the product. The app is effectiveness tracking plus agent recommendations. No live walk-in console. The demo script, README and AppKit design doc are the stale documents. |
| D2 | Story numbers | Keep the current numbers. Step 3 flags a miss and does not fail the build. |
| D3 | Identity and stack | Keep governance code as is (row filter on, `open_to_all` on, names and emails masked as `***`). Keep FastAPI + React. App reads as its service principal. Zerobus and streaming ingest are talking points, not built. |
| D4 | Approval | The agent asks before changing any promotion. Any workspace user can approve. An approval must change what the endpoint sends. |
| D5 | Workspace | `https://dbc-8d181d91-4a82.cloud.databricks.com`. App: `nbo-decision-engine-7474658159680846.aws.databricksapps.com`. |
| D6 | Latency | Endpoint p95 under 200 ms. |

Two rules on screens: screens show KPI labels and live calculated numbers only. Sentences appear only in Genie answers and on recommendation cards, and recommendation content comes from the trained model scoring live data.

## Demo concept

1. **Headline metric: return on spend against the 10.1% target.** Return = incremental margin. Spend = discounts + Databricks compute (`system.billing`) + platform cost. Shown per program and for the pilot, scaled to the network with `finance_assumptions` (13,000 network stores, 15% cannibalization, 45% gross margin, $2.0M platform cost per year; live values).
2. **No individual shoppers on any screen.** Shopper profiles drive the model behind the scenes. Screens show programs, regions and dayparts.
3. **Customer 360, pluggable.** The engine reads one Unity Catalog table or view named by bundle variable `customer_360_table`. The demo ships a sample (`member_features`). A customer points the variable at their table, lists the feature columns, and the uplift model is retrained. Training also needs their past offers with a holdout. Not built (P4).
4. **Real-time decision.** On each check-in `nbo-decision` picks the best offer for that shopper, or none, and holds out 10% of offers for measurement. The retailer's push stack delivers it.
5. **Agent.** The recommender (`nbo_recommender`) scores every program x region and proposes pause, scale, retarget and move-volume changes ranked by profit. A person approves or rejects. An approved change updates campaign state that the endpoint reads on every check-in. Undo restores the prior state.
6. **App at `ceb8d85`.** Overview, Recommendations, Offer programs, Reports (AI/BI dashboard, finance report, export for EPM), How it runs, and a floating Ask Genie. Light by default, dark toggle.
7. **Integration, not standalone.** The retailer's app calls the endpoint, the retailer's push stack delivers, results land in governed tables, and the plan exports to EPM (Anaplan or Jedox file).

## 0. Findings (verified)

Status column: **Resolved** = decided, only documentation or cleanup left. **Gap** = a build item in §12.

| # | Claim in a document | What the code or workspace does | Evidence | Status |
|---|---|---|---|---|
| C1 | Demo script and design doc: live engineer console (In-Store Live, Decision Trace) | App is five tabs plus Genie drawer | Demo Script:64-94; `frontend/src/App.jsx:6-12` | Resolved by D1. Rewrite the three stale documents (P1). |
| C2 | App sends check-ins to `nbo-decision`, logs to `live_decision_log`, sends pushes | `call_decision_service`, `log_decisions`, `push.send` are defined and never called; no route | `app/data.py:225,260`; `app/push.py:74`; `app/server.py` | Resolved by D1. Remove dead code (P1). |
| C3 | "1 in 10 check-ins gets no offer" | Holdout is `event_id % 10` among offer candidates, about 2% of check-ins (live: 17.5% offered, 2.0% control) | Demo Script:31,48; `app/nbo_decision.py:41,197`; live `/api/system` | Gap, wording. Say "10% of offers are held out". |
| C4 | Lakeflow keeps features fresh; Zerobus ingest | No streaming pipeline, no Zerobus code; features built once; step 5 is one `availableNow` run | `src/05_stream_decisions.py:63`; Demo Script:85 | Resolved by D3. Talking point; documents say so. |
| C5 | Governance demo: Texas-only user sees Texas | `open_to_all=true` default: every account user passes the row filter. Names and emails masked. Filter on 10 tables, mask on 6 columns (live). Also grants MODIFY on `live_decision_log` to account users | `src/04_governance.py:20,93,138`; live `information_schema` | Resolved by D3. Governance beat = masking only. |
| C6 | Reads governed per viewer (`*.obo.sql`) | All queries run as the app service principal (SELECT on the schema, MODIFY on `agent_proposals`; live) | `app/data.py:42-51`; `design/appkit-app-design.md:27` | Resolved by D3. |
| C7 | One metric view | Dashboard reads `metrics_promotions`; Genie space from step 8 reads `nbo_offer_metrics`; `genie/genie_space.md` lists a third set. `nbo_offer_metrics` now exists live (built by step 9) | `src/08_agent.py:41-42`; `genie/genie_space.md:9-14` | Gap. Canonical = `nbo_offer_metrics` (P1). |
| C8 | Every request logged to an inference table | Not reproduced. AI Gateway inference table is enabled on `nbo-decision` now, and rows kept landing after the version 8 update on 2026-11-23. Create path sets it, update path does not mention it | live endpoint config; `src/06_serve_decisions.py:215,220` | Gap, small. Add an assertion after update (P1). |
| C9 | p95 round trip shown | Reads `live_decision_log.latency_ms`, which nothing writes, so it is always empty | `app/server.py:217-221` | Gap. Read `execution_duration_ms` from the inference table (P1). Live: p50 50.5 ms, p95 82.8 ms, max 91 ms over 52 requests. |
| C10 | Approving a recommendation changes targeting | Approval updates `agent_proposals` and appends `promotion_changes` (`field='targeting'`, `old_value` empty). Nothing in the decision path reads it. No role check | `app/agent.py:90-125`; `app/nbo_decision.py:150-200` | Gap. Main build item (P2). |
| C11 | Step 3 validates the story | Prints PASS or CHECK, never fails (matches D2). Headline numbers (8,272 check-ins, 17.5% offered, about $44K a year) have no range | `src/03_validate_story.py:27`; `src/nbo_lib.py:821-845` | Gap. Add ranges and a results table, still non-failing (P1). |
| C12 | Design doc: "today Streamlit" | Today FastAPI + React. Two tests still target the Streamlit app | `design/appkit-app-design.md:3`; `tests/test_app_sql.py:84`; `tests/test_bundle_config.py:43` | Gap. Fix both tests (P1). |
| C13 | Screens show labels and numbers only | Verified by scanning `App.jsx`: remaining text is chart titles, empty and error states, reject-reason chips and four suggested Genie questions. Recommendation titles, evidence and rollout are wording templates in `nbo_lib.recommend`, filled with model predictions and live-table numbers. The choice of action is a rule over the model's predictions (pause if the upper bound is below zero, scale if the lower bound is above zero and return clears the hurdle) | `frontend/src/App.jsx:13-18,132,150,153,278,410`; `src/nbo_lib.py:931-1075` | Mostly meets the rule. Wording is code, not model output: see A5. |
| C14 | Genie space comes from `agent_config` | `app.yaml` env wins: app asks "Promotion Performance" (`01f1e5308ffc...`) while the build writes "In-Store NBO Performance" (`01f1e7146f6d...`) | `app/app.yaml:12-13`; `app/agent.py:143-153`; live `agent_config` | Gap. Blank the env value (P1). |
| C15 | Repo describes the workspace | Workspace has objects not in any branch of the repo: table `offer_guardrails` (5 rows, created by the build job 2026-11-21, edited by Ali and by the app service principal), endpoint `nbo-next-best-offer` with model `nbo_next_best_offer`, extra dashboards and Genie space | live reads; `git grep` on every remote branch finds none | Gap. Adopt `offer_guardrails` in step 7 (P2); decide on the rest (P1). |
| C16 | Build job matches `databricks.yml` | Workspace job `[dev ali_chehab] nbo-demo-build` has eight tasks, no `recommender` task. Redeploy on 2026-11-24 uploaded the files and ran step 9 once by hand; the job definition was not changed | live job; `databricks.yml:95-103` | Gap. Run `bundle deploy -t trial` (P1). |
| C17 | Step 9 runs on job compute | It failed on a fresh serverless run: no `mlflow`. Fixed in this branch by adding the same `%pip install` and restart cells that steps 2 and 6 use | `src/09_recommender.py:15-21` | Fixed here. |

## 1. First-principles brief

### Problem
A convenience retailer sends static promotions to every eligible loyalty shopper. About 67% of Coffee + Croissant redemptions would have happened anyway, and incremental margin turned negative after the 1 April rule change. The product decides, per in-store check-in, which of five offers (or none) changes behaviour, hands it to the retailer's push stack, and measures the result against a holdout. (README:5-7; `src/nbo_lib.py:82-111`)

### Primary users and decisions
| Act | User | Decision | Human approval |
|---|---|---|---|
| Real-time decision | Decision service, no human | Offer, no offer, or holdout per check-in | None per check-in. Rules and model. |
| Portfolio | Promotion and finance owner | Pause, scale, retarget, move volume | Approve or reject in the app. Any workspace user (D4). |
| Explain and govern | Data and AI engineering lead (the audience) | Is the path fast, explainable, governed? | None |

P0 presenter journey (D1): Overview, then Recommendations (approve one), then How it runs.

### Non-negotiables
- One shared decision path, `app/nbo_decision.py`, imported by the endpoint, the streaming job and the app (README:33).
- Caller sends three fields: `member_id`, `store_id`, `event_ts` (README:45).
- The decision service never sends notifications; delivery stays with the retailer (README:49).
- Synthetic data only; resource names from bundle variables (`databricks.yml:4-21`).
- No individual shoppers on screen. Screens carry labels and live numbers only; sentences only in Genie and on recommendation cards.

### Success criteria for P0 (D2: keep the numbers, flag a miss, do not fail)
Live values from the 2026-11-24 read in the last column.

| # | Number | Range | Live |
|---|---|---|---|
| 1 | Live-day check-ins, 120 stores | 8,300 +/- 10% (A1) | 8,272 |
| 2 | Share offered | 18% +/- 10% relative (A1) | 17.5% |
| 3 | Backtest uplift, Persuadable / Sure Thing (Coffee + Croissant) | 0.12-0.35 / -0.05-0.08 (`STORY_RANGES`) | read by step 3 |
| 4 | Static-rules discount spend growth after April | 1.5-5.0x; Apr-Sep incremental margin below zero | read by step 3 |
| 5 | Coffee + Croissant redemptions that would happen anyway | 0.55-0.85 | read by step 3 |
| 6 | Annual gain, model vs static rules | $44K +/- 10% on 25,000 shoppers (A1) | read by step 3 |
| 7 | Pilot return on spend vs 10.1% | computed from `offer_performance`, `compute_cost`, `finance_assumptions`; shown, not ranged | live in app |

### Out of scope
Real retailer systems, real push accounts (ntfy for demo), production SLAs, multi-store live rollout, streaming ingest (D3), per-viewer data access (D3), agent invention of new promotions (§13).

## 2. Why Databricks
- **Model Serving + Feature Engineering:** one pyfunc with feature lookup at request time (`src/06_serve_decisions.py:129-223`). Endpoint `nbo-decision`, version 8, Small, scale-to-zero off.
- **Online store:** `nbo-online-store` (CU_1, available), serving `member_features` and `stores` by key (`06:89-114`).
- **MLflow + Unity Catalog registry:** `nbo_uplift_model`, `nbo_decision_service`, `nbo_recommender`, `nbo_next_best_offer` (live).
- **AI Gateway inference table:** `nbo_decision_payload`, enabled (C8).
- **Structured Streaming:** `05_stream_decisions` writes `offer_decisions`. Replay of a table, not live ingest (C4).
- **Unity Catalog:** row filter, PII mask, metric views, grants.
- **Genie and Agent Bricks Supervisor:** the Genie space exists; the Supervisor does not (`agent_config.supervisor_endpoint` is empty). The app falls back to Genie (`app/agent.py:157-226`).
- **Databricks Apps, AI/BI dashboard, Declarative Automation Bundles.**

## 3. Target architecture
```text
generate_data -> train_and_score -> validate_story -> stream_decisions -> serve_decisions
-> governance -> offer_ledger -> recommender -> agent            (databricks.yml:24-103)

retailer app -HTTPS-> nbo-decision (pyfunc) -lookup-> online store (profiles; campaign state in P2)
                          | inference table -> nbo_decision_payload
instore_events -> decisions -> offer_decisions -> offer_outcomes / offer_performance
gold + ledgers -> SQL warehouse -> App | AI/BI dashboard | Genie
recommender -> agent_proposals -> App (Approve / Reject / Undo) -> promotion_changes + campaign_state (P2) -> endpoint
```
Layers: raw (`stores`, `loyalty_members`, `pos_baskets`, `promotions`, `offer_history`, `instore_events`) | features (`member_features`) | models (uplift, decision service, recommender) | gold (`promo_monthly`, `promo_portfolio`, `audience_tiers`, `tier_backtest`, `member_profile`, `member_offer_scores`, `offer_performance`) | ledgers (`offer_decisions`, `offer_outcomes`, `compute_cost`, `promotion_changes`, `agent_proposals`, `agent_activity`, `finance_assumptions`, `agent_config`, `live_decision_log`, and in P2 `campaign_state`) | metrics (`nbo_offer_metrics`).

Data access (D3): service principal reads, FastAPI + React, `open_to_all` on. The attribution header `X-Forwarded-Email` stamps `decided_by`.

## 4. Data contracts
- Keys: `member_id` (`member_features` primary key, `06:102`), `store_id` (`06:144`), `event_id`, `promotion_id` PR01-PR05, `proposal_id`.
- Grains: per `src/07_offer_ledger.py:7-14`.
- Decision response: `decision`, `promotion_id`, `offer_message`, `push_title`, `channel`, `reason`, `expected_net_margin`, `event_id` (README:47; `tests/test_serving_model.py:43`).
- Canonical metric view: `nbo_offer_metrics` (C7).
- **New in P2, `campaign_state`:** one row per `promotion_id` x `region`: `enabled` (boolean), `volume_scale` (double, 1.0 = unchanged), `source_proposal_id`, `changed_by`, `changed_at`. Current state only. History stays in `promotion_changes`, where P2 writes real `field`, `old_value` and `new_value` instead of the current `field='targeting'`, empty `old_value`.
- **Existing, workspace only, `offer_guardrails`:** per promotion `enabled`, `monthly_budget`, `frequency_cap_days`, `holdout_pct`, `margin_floor`, `updated_by`, `updated_at`. Comment in the table: "Policy per promotion that marketing approves." P2 adopts it as the limits table in step 7. The decision path respects `enabled` and `holdout_pct`; budget and caps are recorded, not enforced, in this plan.
- Gap against the Hoonartek standard: no `record_source`, `ingested_at`, `is_synthetic` columns on raw tables; the README objects table omits tables that exist. Both fixed in P1.

## 5. Mock data
- Seed 711, 25,000 members, 120 stores (TX 38, CA 31, FL 27, NE 24), 5 promotions, history 2025-10-01 to 2026-09-30, holdout 0.10, rule change 2026-04-01 (`src/nbo_lib.py:34-60`).
- Generators: `nbo_lib.simulate`, `run_all`. Local build: `local_run.py` writes `.local_data/`.
- `featured_events` fed the retired Decision Trace screen. P1 checks which gold tables only the retired console used (`member_profile`, `member_offer_scores`, `featured_events`) and keeps only what the endpoint, step 5 or the tests still read.
- Quality check: `story_checks`, non-failing (D2).

## 6. Application and agent design
**Screens** (as built, five): Overview (return on spend, KPIs), Recommendations (cards with Approve, Reject with reason, Undo), Offer programs, Reports (AI/BI dashboard embed, finance report, EPM export), How it runs. Floating Ask Genie.

**Recommendation cards** carry model name and version, profit and sales change per year, confidence, evidence and rollout, all from the latest `agent_proposals` run. Live now: five proposals from `nbo_recommender` version 1 (largest: pause Late-Night Energy in Texas, +$879K a year; scale Coffee + Croissant in California by 25%, +$525K).

**Agent boundary:** the agent proposes. It changes nothing until a person approves (D4). Ask Genie answers questions only and triggers no action. New-promotion invention is not in this plan (§13).

**Screen text rule** is enforced by a test (§7): an allowlist of labels, states and Genie prompts; anything longer fails.

## 7. Tests and build gates
Today (2026-11-24, `pytest -q`): **35 pass, 2 fail, 2 skipped.** The two failures: `tests/test_app_sql.py:84` reads removed `app/app.py`; `tests/test_bundle_config.py:43` checks `command[-1]` equals "8000". The two skips need workspace credentials.

Gates to add:
| Gate | Phase |
|---|---|
| Fix the two stale tests | P1 |
| Story check returns every miss and the notebook still exits 0 (D2) | P1 |
| Screen text allowlist over `App.jsx` | P1 |
| Inference table still enabled after an endpoint update | P1 |
| Approved pause removes that program from decisions; Undo restores it (unit, local data) | P2 |
| Approval to endpoint behaviour, live: pause PR05 in Texas, send a fixed set of check-ins, expect no PR05 offers within 2 minutes (A3) | P2 |
| API tests for each route against `.local_data/` | P1 |
| App render smoke test (headless browser, local data) | P1 |
| Endpoint p95 under 200 ms at the load in A2, from the inference table | P3 |
| Customer 360 with renamed columns trains and serves | P4 |

CI: `.github/workflows/tests.yml` runs `pytest -q` on pull requests and pushes to main. Checked 2026-11-24: every run of it on main ends in `startup_failure` (runs 1, 23 and 31 at `7af2ef1`, `6566677`, `ceb8d85`) and this PR has no check runs, so the tests have never run in CI. Cause not investigated; P1 starts there.

## 8. Security
- Reads as the app service principal (D3). Grants verified live: SELECT and USE SCHEMA on the schema, MODIFY on `agent_proposals`; endpoint `CAN_QUERY` (`06:234-240`). Secrets via `valueFrom` (`app/app.yaml`).
- Governance as is (D3): row filter `nbo_region_filter` on 10 tables, mask `nbo_pii_mask` on first name, last name and email of `member_profile` and `loyalty_members`. With `open_to_all` on, every account user sees every row; names and emails show `***`.
- Approvals (D4): any workspace user. Risk: anyone with app access can change live offers. Controls: every approval and undo is written to `promotion_changes` with `changed_by`; Undo is one click; the change takes effect only for the program and region on the card.
- Chat history is client-sent and passed to the supervisor path unvalidated (`app/server.py:270-276`). Keep history server-side (P1).
- No tokens in the repo or in chat. Rotate any token that was ever pasted.

## 9. Resilience and scale (D6)
- Target: endpoint p95 under 200 ms. Measured today from the inference table, server side: p50 50.5 ms, p95 82.8 ms, max 91 ms over 52 requests. That is a small sample, not a load test.
- Load for the gate (A2): the live-day peak is 15 check-ins a minute for the whole pilot (about 0.25 a second), 3 a minute at the busiest store. Scaled to 13,000 stores that is about 27 a second. Gate: **p95 under 200 ms at 30 check-ins a second for 5 minutes**, replaying scaled `instore_events` through a script (not app code). If Small does not hold it, resize and record the final size; if resizing is not worth it for the demo, the hard gate drops to the pilot peak and the 30 a second result is reported.
- Failure behaviour: if the endpoint is slow or down, the caller sends no offer. The decision service never blocks a purchase.
- Warm endpoint: scale-to-zero off.
- App side: gold tables cached 10 minutes (`app/cache.py`); the first request after the SQL warehouse idles waits for it to start (not measured).

## 10. Red-team
| ID | Risk | Sev | Mitigation |
|---|---|---|---|
| RT-01 | Demo script describes screens the app lacks | High | Rewrite README, demo script, design doc (P1) |
| RT-02 | Story numbers drift unnoticed | Medium | Ranges for every headline number; results table; non-failing by D2 (P1) |
| RT-03 | Approval has no effect on offers | High | `campaign_state` read by the decision path (P2) |
| RT-04 | Inference table lost on an endpoint update | Low | Assert after update (P1) |
| RT-05 | p95 shows empty | Medium | Read inference table (P1) |
| RT-06 | App asks a different Genie space than the build wrote | Medium | Blank `GENIE_SPACE_ID` in `app.yaml` (P1) |
| RT-07 | Row filter on `member_features` after online publish | Medium | Verify the online sync accepts a filtered source before P4 |
| RT-08 | Unvalidated chat history | Medium | Server-side history (P1) |
| RT-09 | Anyone can approve a change that costs money | Medium | Audit trail and Undo (§8); an approval cap is a later option |
| RT-10 | Workspace and repo drift (C15, C16) | Medium | `bundle deploy`; adopt or retire workspace-only objects (P1) |
| RT-11 | Recommendation wording is code, not model output | Low | A5; revisit if the rule is meant literally |
| RT-12 | Scale-up has no direct meaning in a model-targeted engine | Medium | A3 defines it; P2 starts with a design spike |

## 11. Lessons applied
Streamlit to React left stale tests (C12). Stale online-table recovery is documented (README:108; `06:62-67`). Configuration comes from bundle variables. One decision module is shared. A build step that fails on a fresh run is caught only by a fresh run: step 9 missed its package install (C17), so P1 adds a fresh-compute run of every notebook to the release checklist.

## 12. Phases and status
**P0, live now (2026-11-24, workspace `dbc-8d181d91-4a82`).**
- App `nbo-decision-engine`: running, redeployed 2026-11-24 08:16 UTC from main (React front end). The earlier Streamlit deployment is replaced.
- Endpoint `nbo-decision`: ready. Endpoint `nbo-next-best-offer`: ready (not in the repo, C15).
- Step 9 run by hand once: registered `nbo_recommender` version 1, wrote five proposals, marked ten earlier open proposals superseded, created metric view `nbo_offer_metrics`.
- App API checked against live tables: overview, recommendations, programs, program detail, system, reports, health all return live data. That check ran the same code locally with the signed-in user's access, not as the app's service principal (its grants were read separately, §8). The app URL itself sits behind workspace sign-in and was not opened from here.
- 31 tables existed before the redeploy; the metric view makes 32 objects.
- `dev` workspace (`dbc-658a2a7c-0afe`) is not the demo workspace and is out of scope.

**P1, trust the numbers and the documents.** Get the `tests` workflow to start (§7). Run `bundle deploy -t trial` so the job gains the `recommender` task (C16). Story ranges for headline numbers plus a `story_checks` table, still non-failing (C11). Fix the two stale tests (C12). Read p95 from the inference table (C9). Assertion on the inference table after update (C8). Blank `GENIE_SPACE_ID` (C14). Canonical metric view and dashboard repoint (C7). Remove dead console code (C2). Rewrite README, demo script and design doc to this plan (C1, C3, C4). Provenance columns and a complete objects table. Screen text allowlist test. Decide what to do with workspace-only objects (C15). *Gate:* `pytest` green; step 3 prints no CHECK on a clean build; "Latency p95" shows a measured value; Ask Genie routes to "In-Store NBO Performance".

**P2, approvals take effect (D4).** Add `campaign_state` and adopt `offer_guardrails` in step 7. Approve writes `campaign_state` and a real `promotion_changes` row; Undo restores the prior row. The state is published to the online store with the same pattern as `member_features` and read in the endpoint's existing lookup; the decision path drops candidates for a paused program and region and applies `volume_scale`. A new model version is served. *Design spike first (RT-12):* confirm the scale-up rule in A3. *Gate:* approve "Pause Late-Night Energy in Texas", send fixed Texas check-ins, no PR05 offer within 2 minutes; Undo, and offers return.

**P3, latency gate (D6).** Replay script, 30 a second for 5 minutes, p95 read from the inference table. *Gate:* under 200 ms, or the fallback in §9.

**P4, pluggable Customer 360.** `customer_360_table` variable, feature columns from config, training and endpoint read it. *Gate:* tests pass on the sample and on a renamed-column copy; rebuild in `trial` and the endpoint still returns decisions.

**P5, not scheduled.** Agent proposes new promotions, not only changes to existing ones.

## 13. Coverage map
| Capability | Status |
|---|---|
| Customer 360 features | Sample built (`member_features`) |
| Plug in an existing Customer 360 | Not built (P4) |
| Real-time per-shopper decision | Built, live, p95 83 ms server side on a small sample |
| Recommender proposes pause, scale, retarget, move | Built (`nbo_recommender`), live, five proposals |
| Approve, Reject, Undo recorded | Built (`agent_proposals`, `promotion_changes`) |
| Approval changes what the endpoint sends | Not built (P2) |
| Return on spend against 10.1%, per program | Built (Overview, Offer programs) |
| One metric view | Built (`nbo_offer_metrics`); dashboard repoint pending (P1) |
| Export for EPM | Built (`/api/reports/epm.csv`) |
| Ask Genie | Built; wrong space pinned (C14) |
| Supervisor agent | Not present in the workspace; Genie used directly |
| Agent invents new promotions | Not built (P5) |
| Streaming ingest, Zerobus | Talking point (D3) |

## 14a. Decisions
Answered in the table at the top. Source: Ali, 2026-11-24, accepting the recommended answers for D2, D4 and D6 and the earlier calls for D1, D3 and D5. Changes against the earlier draft of this file: D2 was "fail the build on a miss", now flag only. D4 was "agent acts alone within limits (up to 20% scale, pause below 10.1%), bigger moves wait", now the agent asks before every change. D6 was "measured, no hard gate", now p95 under 200 ms.

## 14b. Defaults chosen in this plan (change any)
| # | Default | Why |
|---|---|---|
| A1 | Tolerance +/- 10% on check-ins, share offered, annual gain | `STORY_RANGES` has no range for these three; 10% is a starting point |
| A2 | Latency load: 30 check-ins a second for 5 minutes | Scaled live-day peak (about 27 a second at 13,000 stores) |
| A3 | Scale-up means lowering the Persuadable uplift cutoff until the offered share rises by the proposal's step (`SCALE_STEP` = 25%, `src/nbo_lib.py:862`); scale-down and pause use event sampling and the enabled flag. Propagation target: 2 minutes | The engine only offers to Persuadables, so volume can only grow by widening that set |
| A4 | No per-approver role check; audit trail and Undo instead | D4: any workspace user |
| A5 | Recommendation wording stays templated around model-scored numbers | Numbers and the choice of action come from the model; free-text generation adds variance. Revisit if the rule means model-written sentences |

## 15. Definition of done
- `pytest` green, including the two repaired tests, the story check, the screen-text test and the approval-to-decision test.
- From a clean `bundle deploy -t trial` and job run: endpoint returns a decision per check-in; recommender proposes; approving a pause stops that program's offers at the endpoint within 2 minutes; Undo restores them; the app and dashboard show the result and `promotion_changes` records who and when.
- Endpoint p95 under 200 ms by the gate in §9.
- The app screens pass the text rule; recommendations come from the latest `nbo_recommender` run.
- README, demo script, this plan and `design/architecture.json` describe the same product.
