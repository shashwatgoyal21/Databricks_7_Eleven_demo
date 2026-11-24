# Real-Time NBO Decision Engine — Implementation Plan (draft)

> Status: **Concept not ready.** 9 of 15 sections fillable from the repo; 6 owner decisions block the rest (§14a). · 2026-11-24
> Baseline: `chehaba/databricks-app` @ `ceb8d85` (main). Canonical intent today: `README.md` + `NBO - Demo Script.md` + `design/appkit-app-design.md` — these disagree with the shipped app (§0).
> All shoppers, stores, numbers and the retailer brand are fictional.
> Method: drafted from the repo + live dev workspace read-only checks; independently audited by an advisor (Plan agent). Every fact below is cited or marked OPEN.

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

## 6. Application and agent design — OPEN D1
Built: 5 tabs + Genie drawer (`App.jsx`). Designed: 4 screens + routes `POST /api/checkin`, `POST /api/decision-log` (`design/appkit-app-design.md:13-28`).
Agent boundaries (built): Supervisor routes to Genie space `nbo_performance`; chat falls back to Genie, then local text (`app/agent.py:157-226`). **OPEN:** can an agent answer ever trigger an action, or Q&A only; Genie table set (C7).

## 7. Tests and build gates (partial)
Existing: SQL-vs-schema, bundle config, SDK signature, serving model contract, live workspace (skipped without creds). Run on 2026-11-24: **35 pass, 2 fail, 2 skipped** (`tests/test_app_sql.py:84` reads removed `app/app.py`; `tests/test_bundle_config.py:43` checks `command[-1]`="8000").
Missing: story oracle as hard test (needs D2), app render/E2E test, agent eval, latency gate (needs D6).

## 8. Security — OPEN D3, D4
Built: UC row filter + PII mask (`04_governance.py`), endpoint `CAN_QUERY` grant to app SP (`06:234-240`), secrets via `valueFrom` (`app/app.yaml`). Gaps: SP-only reads (C6), filter open to all (C5), no approver role check (C10), client-sent chat history passed to supervisor unvalidated (`app/server.py:273-279`).

## 9. Resilience and scale — OPEN D6
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
- **P0a local:** build + app run locally; live console not built (C1-C2); 2 tests red.
- **P0b workspace:** dev workspace (`dbc-658a2a7c-0afe`, read 2026-11-24): endpoint `nbo-decision` **does not exist**; app **STOPPED** ("workspace or account status"); 15 tables from an older build (no `instore_events`, `offer_decisions`, `live_decision_log`, `offer_performance`, `agent_proposals`); no `nbo-demo-build` job; no Lakebase instances. `trial` (default target) not inspectable from here.
- P1+ cannot be sequenced until D1.

## 13. Coverage map — fillable after D1

## 14a. Owner decisions blocking completion
1. **D1 Product scope:** P0 = live decision console (Acts 1–4), current finance/portfolio console, or both?
2. **D2 Oracle:** exact numbers + tolerances; does step 3 fail the build on a miss?
3. **D3 Identity/stack:** OBO or SP for reads; `open_to_all`; keep FastAPI+React or rebuild on AppKit; Zerobus/SDP in scope?
4. **D4 Approval:** does approving change the live decision path, and who may approve?
5. **D5 Workspace:** `trial` or `dev`; do the 6 groups, Lakebase, Model Serving, Agent Bricks exist there; push provider/topic; Genie space ID.
6. **D6 Latency:** p95 targets for endpoint and app round trip, at what check-in rate.

## 15. Definition of done — needs D1, D2, D6

