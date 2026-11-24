# Agentic Next Best Offer — Implementation Plan

> Status: **Concept defined 2026-11-24. Build not started.** Workspace is chosen with the customer at engagement. Decisions in §14a.
> Baseline: `chehaba/databricks-app` @ `ceb8d85` (main). Canonical intent today: `README.md` + `NBO - Demo Script.md` + `design/appkit-app-design.md` — these disagree with the shipped app (§0).
> All shoppers, stores, numbers and the retailer brand are fictional.
> Method: drafted from the repo + live dev workspace read-only checks; independently audited by an advisor (Plan agent). Every fact below is cited or marked OPEN.

## Demo concept (decided 2026-11-24)

1. **Customer 360 (pluggable).** The engine reads one Unity Catalog table or view, set by a bundle variable `customer_360_table`. It needs one row per customer, a customer ID key, and the feature columns listed in config. The demo ships a sample Customer 360 (today's `member_features`). A customer plugs in theirs by pointing the variable at their table, or at a mapping view over it. The uplift model is then retrained on their columns. Training also needs their past offers with a holdout (their equivalent of `offer_history`); the Customer 360 alone is not enough to learn uplift.
2. **Real-time decision.** On each check-in, the `nbo-decision` endpoint picks the best offer for that shopper in milliseconds, or none. Automatic, no human. Push delivery stays with the retailer's stack and is not shown in the demo.
3. **Campaign agent.** Watches results and starts, stops and scales offers on its own within guardrails. No approval queue; a human can revert. The decision endpoint reads the live campaign state on every check-in.
4. **Dashboard.** Shows what the agent did (started, stopped, scaled), why, and the profit impact.

## 0. Concept contradictions found (verified)

| # | Concept says | Code does | Evidence |
|---|---|---|---|
| C1 | App = live engineer console: In-Store Live, Decision Trace, Under the Hood, Does the Model Work? | App = finance/portfolio console: Overview, Recommendations, Offer programs, Reports, How it runs + Genie drawer | Demo Script:64-94; `frontend/src/App.jsx:6-12` |
| C2 | App sends check-ins to `nbo-decision`, logs to `live_decision_log`, sends real pushes | `call_decision_service`, `log_decisions`, `push.send` defined, never called; no route | `app/data.py:225,260`; `app/push.py:74`; `app/server.py` |
| C3 | "1 in 10 check-ins gets no offer" | Holdout = `event_id % 10` among offer candidates (~2% of check-ins) | Demo Script:31,48; `app/nbo_decision.py:197` |
| C4 | Lakeflow keeps `member_features` fresh; Zerobus ingest | No SDP pipeline, no Zerobus code; features built once; step 5 is one `availableNow` run reading batch scores, not the online store | `src/05_stream_decisions.py:63`; Demo Script:85 |
| C5 | Governance demo: Texas-only user sees Texas | `open_to_all=true` default → row filter passes all account users; also grants MODIFY on `live_decision_log` to all | `src/04_governance.py:20,93,138` |
| C6 | Reads governed per viewer (design: `*.obo.sql`) | All queries run as app service principal | `app/data.py:42-51`; `design/appkit-app-design.md:27` |
| C7 | One metric view | Dashboard uses `metrics_promotions`; Genie space from step 8 uses `nbo_offer_metrics`; `genie/genie_space.md` lists a third table set | `src/08_agent.py:41-42`; `genie/genie_space.md:9-14` |
| C8 | Every request logged to inference table | Only on create; update path drops `ai_gateway` | `src/06_serve_decisions.py:214-215` |
| C9 | p95 round trip shown | Reads `live_decision_log.latency_ms`, which nothing writes → always null | `app/server.py:216-218` |
| C10 | Approving a recommendation changes targeting | Approval appends `promotion_changes`; nothing in the decision path reads it; no approver role check | `app/agent.py:90-125` |
| C11 | Step 3 validates the story | Prints PASS/CHECK only; never fails the job; headline numbers (~8,300 / ~18% / ~$44K) unchecked | `src/03_validate_story.py:27`; `src/nbo_lib.py:838-845` |
| C12 | Design doc: "today Streamlit", rebuild on AppKit | Today FastAPI + React (Vite), tests still reference Streamlit | `design/appkit-app-design.md:3`; `tests/test_bundle_config.py:58` |

## 1. First-principles brief

### Problem
A convenience retailer sends static promotions to every eligible loyalty shopper; ~67% of Coffee + Croissant redemptions would have happened anyway and incremental margin turned negative after the Apr 1 rule change. The demo shows deciding, per in-store check-in, which of five offers (or none) changes behaviour, delivered through the retailer's existing push stack, measured against a holdout. (README:5-7; `src/nbo_lib.py:82-111`)

### Primary users and decisions
| Act | User | Decision | Human approval |
|---|---|---|---|
| Real-time decision | Decision service (no human in loop) | Offer / No offer / Holdout per check-in | None — rules + model; **OPEN D4** |
| Explain & govern | Data/AI engineering lead (audience) | Is the path fast, explainable, governed? | — |
| Portfolio | Promotion/finance owner | Pause / scale / retarget / move volume | Approve/reject in app (`agent_proposals`) |

**OPEN D1:** which of these is the P0 presenter's journey (C1).

### Non-negotiables (from repo)
- One shared decision path, `app/nbo_decision.py`, imported by endpoint, streaming job and app (README:33).
- Caller sends 3 required fields (`member_id`, `store_id`, `event_ts`) (README:45).
- Decision service never sends notifications; delivery stays with the retailer's push stack (README:49).
- Synthetic data only; resource names from bundle variables (`databricks.yml:4-21`).

### Success criteria for P0 — **OPEN D2**
Candidate oracle (from README:121-134 and `STORY_RANGES`, `src/nbo_lib.py:821-835`):
1. ~8,300 live-day check-ins across 120 stores (no range coded).
2. ~18% offered, ~80% suppressed (no range coded).
3. Coffee + Croissant backtest uplift: Persuadable 0.12–0.35, Sure Thing −0.05–0.08.
4. Static-rules discount spend growth after April 1.5–5.0×; Apr–Sep incremental margin < 0.
5. Coffee + Croissant redemptions that would happen anyway 0.55–0.85.
6. Annual gain model vs static ~$44K (no range coded).
Missing: exact tolerances for 1, 2, 6; whether a miss fails the job.

### Out of scope for P0 (from repo)
Real retailer systems, real push accounts (ntfy for demo), production SLAs, multi-store live rollout.

## 2. Why Databricks (fillable)
- **Model Serving + Feature Engineering:** one pyfunc with feature lookup at request time (`src/06_serve_decisions.py:129-223`).
- **Lakebase online store:** `member_features`, `stores` served by key (`06:89-114`).
- **MLflow + UC registry:** `nbo_uplift_model`, `nbo_decision_service@prod`, `nbo_recommender`.
- **AI Gateway inference table:** `nbo_decision_payload` (C8 caveat).
- **Structured Streaming:** `05_stream_decisions` → `offer_decisions`.
- **Unity Catalog:** row filter, PII mask, metric views, grants (C5 caveat).
- **Genie + Agent Bricks Supervisor:** "NBO Offer Agent" (`src/08_agent.py`).
- **Databricks Apps, AI/BI dashboard, Declarative Automation Bundles.**

## 3. Target architecture
Logical flow (as built):
```text
generate_data → train_and_score → validate_story → stream_decisions → serve_decisions
→ governance → offer_ledger → recommender → agent          (databricks.yml:24-97)

check-in ─HTTPS─> nbo-decision (pyfunc) ─lookup─> Lakebase online store
                     │ inference table ─> nbo_decision_payload
instore_events ─> streaming decisions ─> offer_decisions ─> offer_outcomes/offer_performance
gold + ledgers ─> SQL warehouse ─> App · AI/BI dashboard · Genie ─> Supervisor
```
Layer responsibilities: raw (`stores`, `loyalty_members`, `pos_baskets`, `promotions`, `offer_history`, `instore_events`) · features (`member_features`) · models (uplift, decision service, recommender) · gold (`promo_monthly`, `promo_portfolio`, `audience_tiers`, `tier_backtest`, `featured_events`, `member_profile`, `member_offer_scores`) · ledgers (`offer_decisions`, `offer_outcomes`, `offer_performance`, `compute_cost`, `promotion_changes`, `agent_proposals`, `agent_activity`, `finance_assumptions`, `agent_config`, `live_decision_log`).

**Data access decision gate — OPEN D3:** OBO (as designed, C6) or service principal (as built); FastAPI+React (as built) or AppKit rebuild (design doc, C12); Zerobus/SDP in scope or talk track (C4).

## 4. Canonical data contracts (fillable; one choice open)
- Keys: `member_id` (`member_features` PK, `06:102`), `store_id` (`06:144`), `event_id` (decisions), `promotion_id` PR01–PR05, `proposal_id`.
- Grains: per `src/07_offer_ledger.py:7-14`.
- Decision response contract: `decision`, `promotion_id`, `offer_message`, `push_title`, `channel`, `reason`, `expected_net_margin`, `event_id` (README:47; `tests/test_serving_model.py:43`).
- Gap vs Hoonartek standard: no `record_source` / `ingested_at` / `is_synthetic` columns; README objects table omits 10 tables (advisor #11).
- **OPEN:** canonical metric view — `metrics_promotions` or `nbo_offer_metrics` (C7).

## 5. Mock-data generation (fillable)
- Seed 711, 25,000 members, 120 stores (TX 38 / CA 31 / FL 27 / NE 24), 5 promotions, history 2025-10-01 → 2026-09-30, holdout 0.10, policy change 2026-04-01 (`src/nbo_lib.py:34-60`).
- Generators: `nbo_lib.simulate`, `run_all`; local build `local_run.py` → `.local_data/`.
- Story fixtures: `featured_events` (Decision Trace cases); hero promotion PR01.
- Quality check: `story_checks` (non-failing — C11).

## 6. Application and agent design
**Target (D1):** screens = Agent activity (what it started, stopped, scaled, why, impact) · Programs (status, return vs target) · Customer 360 (one shopper's profile and the offer they'd get now) · Ask the agent. Guardrails shown and editable by a human; Revert on every agent action.

As built:
Built: 5 tabs + Genie drawer (`App.jsx`). Designed: 4 screens + routes `POST /api/checkin`, `POST /api/decision-log` (`design/appkit-app-design.md:13-28`).
Agent boundaries (built): Supervisor routes to Genie space `nbo_performance`; chat falls back to Genie, then local text (`app/agent.py:157-226`). **OPEN:** can an agent answer ever trigger an action, or Q&A only; Genie table set (C7).

## 7. Tests and build gates (partial)
Existing: SQL-vs-schema, bundle config, SDK signature, serving model contract, live workspace (skipped without creds). Run on 2026-11-24: **35 pass, 2 fail, 2 skipped** (`tests/test_app_sql.py:84` reads removed `app/app.py`; `tests/test_bundle_config.py:43` checks `command[-1]`="8000").
Missing: story oracle as hard test (needs D2), app render/E2E test, agent eval, latency gate (needs D6).

## 8. Security (D3, D4 decided: SP reads, agent acts within guardrails)
Built: UC row filter + PII mask (`04_governance.py`), endpoint `CAN_QUERY` grant to app SP (`06:234-240`), secrets via `valueFrom` (`app/app.yaml`). Gaps: SP-only reads (C6), filter open to all (C5), no approver role check (C10), client-sent chat history passed to supervisor unvalidated (`app/server.py:273-279`).

## 9. Resilience and scale (D6: measured, no hard gate)
Claims without gates: "within a second", "~50 ms local", p50/p95 KPI (C9). No load target, no check-in rate.

## 10. Red-team (fillable)
| ID | Risk | Sev | Mitigation |
|---|---|---|---|
| RT-01 | Demo script shows screens the app lacks | Critical | Resolve D1 |
| RT-02 | Story numbers drift with no failing check | High | Make step 3 fail on miss (D2) |
| RT-03 | Governance demo shows all regions | High | `open_to_all=false` + region groups (D3) |
| RT-04 | Inference table missing after endpoint update | High | Pass `ai_gateway` on update path (`06:214`) |
| RT-05 | Approval has no effect on decisions | High | Wire `promotion_changes` into decision path or relabel (D4) |
| RT-06 | p95 always "Not measured" | Medium | Write `latency_ms` or read inference table |
| RT-07 | Genie space ID hard-coded to one workspace overrides `agent_config` | Medium | Empty default in `app.yaml:12-13` |
| RT-08 | Row filter on `member_features` after online publish | Medium | Verify online sync accepts filtered source |
| RT-09 | Unvalidated chat history to supervisor | Medium | Server-side history |

## 11. Lessons applied (fillable)
Streamlit → React migration left stale tests (C12); stale online table recovery documented (README:108; `06:62-67`); config via bundle variables; shared decision module.

## 12. Phases and honest status
- **P0a local:** `local_run.py` builds the synthetic data and the app runs locally. `pytest` 35 pass, 2 fail (stale Streamlit-era tests). The demo script's live console is dropped (D1), so C1–C2 no longer block.
- **P0b workspace — `trial` (`dbc-8d181d91-4a82`, read 2026-11-24): live.** App `nbo-decision-engine` RUNNING (deployed 2026-11-23); endpoints `nbo-decision` and `nbo-next-best-offer` READY; warehouse `7b83e80f825c883f` RUNNING; job `[dev ali_chehab] nbo-demo-build` last run SUCCESS 2026-11-23 08:13 UTC; 31 tables in `workspace.nbo_demo` incl. `nbo_decision_payload`, `offer_decisions`, `live_decision_log`, `offer_performance`, `agent_proposals`; Genie spaces "In-Store NBO Performance" and "Promotion Performance"; dashboard "[dev ali_chehab] NBO Offer Engine". In the workspace but not in this repo: table `offer_guardrails` (`promotion_id, enabled, monthly_budget, frequency_cap_days, holdout_pct, margin_floor, updated_by, updated_at`, created 2026-11-21) and endpoint `nbo-next-best-offer`. No supervisor endpoint, no Lakebase database instances listed.
- **`dev` (`dbc-658a2a7c-0afe`):** app stopped for workspace/account status; older build. Not the demo workspace.
- **P1 — Pluggable Customer 360 (next).** `customer_360_table` bundle variable, feature columns from config, training and endpoint read that table; sample `member_features` stays the default. Gate: tests pass on the sample and on a renamed-column Customer 360; rebuild in `trial` and the endpoint still returns decisions.
- **P2 — Agent applies campaign changes.** Campaign state (on/off, budget, caps, margin floor) read by the decision path on every check-in; the agent starts, stops and scales within guardrails; human revert. Builds on `offer_guardrails` in `trial` once its origin is confirmed. Gate: pausing a program stops its offers at the endpoint.
- **P3 — Agent activity screens.** App and dashboard show what the agent started, stopped and scaled, why, and the profit impact.
- **P4 — Hardening.** Step 3 fails the build on a story-number miss, stale tests fixed, README and demo script match the agentic concept.

## 13. Coverage map
| Capability | Status |
|---|---|
| Customer 360 features | Sample built (`member_features`) |
| Plug in an existing Customer 360 | Not built: `customer_360_table` variable, feature-column config, retrain on their columns |
| Real-time per-customer decision | Built (endpoint), not deployed in dev |
| Agent proposes start/stop/scale | Built as proposals (`nbo_recommender`) |
| Agent applies changes within guardrails | Not built: needs campaign state read by the decision path |
| Dashboard of agent actions and impact | Not built: current pages are Executive, Real-time decisions, Is the model right? |
| New campaigns invented by the agent | Not built; out of scope for first demo |

## 14a. Owner decisions
1. **D1 Product scope — decided.** Agentic campaign demo (see *Demo concept*). Per-check-in decision and push are plumbing under it. The Acts 1–4 live console in the demo script is replaced.
2. **D2 Oracle — decided.** Use `STORY_RANGES` (`src/nbo_lib.py:821-835`); step 3 fails the build on a miss. Add agent oracle: on the fixture, the agent pauses at least one program below the return target and scales the top program.
3. **D3 Identity/stack — decided.** Keep FastAPI + React as built; reads as the app service principal; `open_to_all` stays on; Zerobus is talk track only.
4. **D4 Approval — decided.** No approval queue. The agent applies changes within guardrails: budget cap, minimum offers before acting, auto-pause below the return target, maximum change per run. A human can revert.
5. **D5 Workspace — decided.** Demo builds and runs in `trial` (the bundle default, live). A customer deployment's workspace is chosen with the customer at engagement.
6. **D6 Latency — decided.** Show measured latency from the inference table; no hard gate for the demo.

## 15. Definition of done
- `pytest` green, including the 2 stale tests fixed and a failing-on-miss story oracle.
- From a clean build in the chosen workspace (D5): endpoint returns a per-shopper decision; agent run pauses at least one losing program and scales the top one; the decision endpoint honours the new campaign state; dashboard and app show those actions with reasons and impact; a human revert restores the prior state.
- README, demo script, plan and `design/architecture.json` describe the same demo.

