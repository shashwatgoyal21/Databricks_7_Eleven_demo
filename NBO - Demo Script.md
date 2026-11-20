# Next Best Offer Decision Engine — Promotion Performance Demo

> **What this is.** A fast, end-to-end demo of a Next Best Offer engine built on Databricks, using synthetic convenience-retail loyalty data. Promotion spend has tripled since April, but incremental margin went negative. The dashboard shows the problem, Genie explains it in plain English, and the optional **Next Best Offer app** shows marketers what they'd actually use: which offers to run, who to send them to, why each shopper gets the offer they get, and an Approve button that writes the decision back to Unity Catalog. Synthetic data → Lakeflow Jobs build → uplift model in MLflow → governed metric view → Databricks App + AI/BI Dashboard + Genie, with row filters and PII masks.

All members, stores, and numbers in this demo are fictional. The build kit is in the `nbo-demo` folder.

## The Story

| | |
| --- | --- |
| **Company** | A fictional convenience retailer: 120 stores across Texas, California, Florida, and the Northeast, with a loyalty pilot of 25,000 members |
| **Hero** | The **VP of Loyalty & Personalization**, asked to justify a promotion budget that has tripled |
| **Question** | We're sending more offers than ever and redemption looks great. **Are we buying any extra sales?** |
| **Investigation** | POS baskets, the loyalty CRM, the promotion catalog, and offer history with a 10% holdout on every send, unified in Unity Catalog. On **2026-04-01** the team stopped curating sends and started sending every offer to everyone eligible. Monthly discount spend went from **~$2.0K to ~$8.3K**. Monthly incremental margin went from **+$500 to −$2.3K**. Why? |
| **Root cause** | Redemption rate counts everyone who used the offer, including shoppers who would have bought anyway. **Coffee + Croissant** redeems at **38%**, but the holdout shows **67% of those redemptions would have happened without the offer**: about 40% of morning commuters already add a pastry to most coffee visits. They redeem the most and are moved the least. |
| **Impact** | Score every shopper twice, with and without the offer, and only send to the ones it moves. For Coffee + Croissant that turns **−$1.1K per send into +$700 per send**. Across the portfolio, about **$44K a year** on a 25,000-member pilot, scaling linearly with members. |

## Overview

The demo date is **2026-09-30**. Basket history runs October 2025 → September 2026; offer history covers January → September 2026, one send per promotion per month, each with a 10% holdout. Until March, marketers hand-picked small segments. From April every offer went to everyone eligible. The holdout makes the real effect measurable: it is grounded in the data, not assumed. The uplift model is trained on the January–March sends and checked against April–September: members it calls **Persuadable** show **~+22 pts** measured lift on Coffee + Croissant; members it calls **Sure Thing** show **~0**.

## Key Numbers

| Metric | Value |
| --- | --- |
| Loyalty members (pilot) | 25,000 |
| POS baskets | ~3.3M, Oct 2025 → Sep 2026 |
| Offers sent | ~187K, Jan → Sep 2026, 10% holdout each |
| Policy change | 2026-04-01: send to all eligible |
| Monthly discount spend | ~$2.0K (Jan–Mar) → ~$8.3K (Apr–Sep), +326% |
| Monthly incremental margin | ~+$500 → ~−$2.3K |
| Coffee + Croissant redemption rate | ~38% |
| Coffee + Croissant redemptions that would happen anyway | ~67% |
| Coffee + Croissant net margin per send | All eligible ~−$1.1K · Propensity-ranked ~−$1.5K · Uplift-targeted ~+$700 |
| Measured lift, Persuadable vs Sure Thing | ~+22 pts vs ~0 pts |
| Annual gain from uplift targeting | ~$44K on the pilot base |
| Late-Night Energy $1 Off | No audience pays back: retire or redesign |

## Demo Walkthrough

**Frame:** *"Promotion spend has tripled since April. Let's see what it's buying on the dashboard, then ask Genie why, in plain English."*

### 1. Spot the risk (1 min)

Open the **AI/BI Dashboard**, page "Is promo spend working?". The KPI cards show monthly discount spend up from ~$2.0K to ~$8.3K since April, and monthly incremental margin, measured against the 10% holdout, down from ~+$500 to ~−$2.3K. The spend-vs-margin line shows the two crossing at the 2026-04-01 policy change. Redemption looks healthy, so nobody noticed.

### 2. Find the driver (1 min)

Switch to page "Where is the waste?". The redemption-vs-lift bars single out **Coffee + Croissant**: the tallest redemption bar (~38%) with a short lift bar, because ~67% of its redemptions would have happened anyway. The tier chart shows the uplift model's Persuadables at ~+22 pts measured lift and Sure Things at ~0. The portfolio table shows uplift targeting turns Coffee + Croissant from ~−$1.1K to ~+$700 per send, and that Late-Night Energy $1 Off pays back for no audience.

### 3. Ask why, in Genie (1–2 min)

Open the **Genie space**. Ask *"Why did discount spend go up after April but incremental margin go down?"* → spend roughly tripled when every offer went to everyone eligible, and margin turned negative. *"Which promotion has the biggest gap between redemption rate and real lift?"* → Coffee + Croissant: about two thirds of redemptions would have happened anyway. *"What would targeting only persuadable shoppers be worth?"* → ~+$700 per send on Coffee + Croissant, ~$44K a year across the portfolio. Genie traces it across sends, holdouts, redemptions, and the model tiers.

### Optional: act on it (2–3 min)

If the audience wants to see the action layer, open the **Next Best Offer** Databricks App on the same tables. **Target Audience**: pick Coffee + Croissant and flip the strategy (all eligible ~−$1.1K, propensity ~−$1.5K, uplift ~+$700), then click **Approve** to write the decision to `campaign_approvals` in Unity Catalog. **Customer-Level View**: Kevin gets the offer (it moves him from 6% to 31%); Hannah doesn't (she already adds a pastry on 63% of coffee visits). For governance, sign in as a Texas marketing manager: the dashboard and Genie show Texas only, and names and emails come back as `***`.

### Closing

*"Your team sees what each promotion really earns, asks why in plain English, and acts on it in an app running inside your own Databricks workspace, on governed data, with every decision written back. It deploys from packaged code, so the next promotion, region, or brand is a configuration change, not a new project."*

## Products Showcased

| Product | Mode | What it does in this demo |
| --- | --- | --- |
| Synthetic data generation | Build | Stores, loyalty members, POS baskets, promotion catalog, and offer history with holdouts |
| Lakeflow Jobs | Build | Runs the build: raw tables → `member_features` → scores → gold tables |
| MLflow + Unity Catalog model registry | Build | Two-model uplift learner per promotion, logged and registered as `nbo_uplift_model` |
| Unity Catalog Metric View | Build | `metrics_promotions`: sends, redemptions, holdout rate, measured lift, discount spend, incremental margin |
| Unity Catalog row filters and column masks | Build | Regional marketers see only their region; names and email masked without `loyalty_pii` |
| Databricks Apps | Build | The Next Best Offer app: portfolio, audience targeting, 1-to-1 explanations, measurement, approve and write back |
| AI/BI Dashboard | Build | Spend vs incremental margin, redemption rate vs measured lift, lift by model tier |
| AI/BI Genie | Build | Natural-language "why", traced to Coffee + Croissant and sure-thing redemptions |
| Databricks Asset Bundles | Build | Deploys the job, notebooks, and app into a new workspace in one command |
| Lakeflow Connect | Talk track | How POS, loyalty CRM, and offer-platform data land in the lakehouse |
| Model Serving | Talk track | Real-time scoring at the POS pin-pad and in the app as a basket is scanned |
| Agent Bricks | Talk track | A promotions agent that drafts campaign briefs from the same governed data |
| Genie on Databricks One | Talk track | The same Genie space for loyalty leaders on their phone |

## Before recording

- Read the numbers off the app and dashboard after the first build and update the tables above. Step 3 prints them.
- Swap in the source systems, promotion names, and access groups the client actually uses.
- Record the walkthrough as a video of 5 minutes or less.
- Keep a copy of the synthetic workspace a Databricks SA can run without us on the call.
