# Next Best Offer demo: build kit

Builds the synthetic loyalty data, uplift model, gold tables, metric view, access rules, and the Next Best Offer app for the convenience-retail promotions demo. The dashboard and Genie space are assembled in the UI from the files in `dashboard/` and `genie/`. All members, stores, and numbers are fictional.

## What gets built

| Object | Type | Purpose |
| --- | --- | --- |
| `stores` | Table | 120 stores across Texas, California, Florida, Northeast |
| `loyalty_members` | Table | Members, region, CRM segment, opt-ins (names and email masked) |
| `pos_baskets` | Table | ~3.3M POS baskets, Oct 2025 → Sep 2026, with category flags |
| `promotions` | Table | The five promotions with discount cost and unit margin |
| `offer_history` | Table | Every 2026 send with Treatment / Holdout group and conversion |
| `member_features` | Table | Silver: visit mix, category rates, recency per member |
| `nbo_uplift_model` | Registered model | Two response models per promotion (with offer, without offer) |
| `member_offer_scores` | Table | Member × promotion: likelihood with and without offer, lift, net margin, tier, next best offer |
| `member_profile` | Table | Member behaviour and next best offer, for the customer view |
| `promo_monthly` | Table | Gold: month × promotion × region sends, redemptions, holdout, spend, incremental margin |
| `promo_portfolio`, `audience_tiers`, `tier_backtest`, `featured_members` | Tables | Gold tables read by the app |
| `metrics_promotions` | Metric view | Governed KPIs read by the dashboard and Genie |
| `loyalty_region_filter` | Function | Row filter by marketing region |
| `loyalty_pii_mask` | Function | Names and email visible only to `loyalty_pii` |
| `campaign_approvals` | Table | Written by the app's Approve button |
| `nbo-decision-engine` | Databricks App | The marketer-facing app |

## Prerequisites

- A Unity Catalog workspace with serverless jobs, or a cluster on DBR 15.4 LTS or later.
- A Pro or Serverless SQL warehouse for the app, dashboard, and Genie.
- Databricks Apps enabled in the workspace.
- Account groups: `loyalty_leadership`, `marketing_texas`, `marketing_california`, `marketing_florida`, `marketing_northeast`, `loyalty_pii`.
- Add yourself to `loyalty_leadership`, or you'll see no rows after step 4.

## Run it

With the Databricks CLI:

```bash
databricks bundle deploy -t dev --var="catalog=workspace" --var="schema=nbo_demo" --var="warehouse_id=<warehouse id>"
databricks bundle run -t dev nbo_demo_build
databricks bundle run -t dev nbo_app
```

If you change the catalog or schema, also change `NBO_SCHEMA` in `app/app.yaml`.

Without the CLI: import the four notebooks and `nbo_lib.py` from `src/` into one workspace folder, set the `catalog` and `schema` widgets, and run the notebooks in order. Then create an app from `app/` in **Compute > Apps** and attach the SQL warehouse as a resource named `sql-warehouse`.

| Step | Notebook | What it does |
| --- | --- | --- |
| 1 | `01_generate_data.py` | Simulates Oct 2025 → Sep 2026 and writes the raw tables (about 3 minutes) |
| 2 | `02_train_and_score.py` | Builds features, trains and registers the uplift model, scores members, writes gold |
| 3 | `03_validate_story.py` | Checks the story numbers and prints PASS or CHECK for each |
| 4 | `04_governance.py` | Creates the metric view, row filter, PII mask, approvals table, and grants |

Rerunning the job rebuilds everything except `campaign_approvals`.

## Finish in the UI

1. **Give the app access.** Find the app's service principal on its page in **Compute > Apps**. Add it to `loyalty_leadership`, then:
   ```sql
   GRANT USE CATALOG ON CATALOG workspace TO `<app service principal>`;
   GRANT USE SCHEMA, SELECT ON SCHEMA workspace.nbo_demo TO `<app service principal>`;
   GRANT MODIFY ON TABLE workspace.nbo_demo.campaign_approvals TO `<app service principal>`;
   ```
2. Build the dashboard from `dashboard/datasets.sql` and `dashboard/layout.md`, about 20 minutes.
3. Create the Genie space from `genie/genie_space.md`, about 10 minutes.
4. Test governance: sign in as a user who is only in `marketing_texas`. The dashboard and Genie should show Texas only, and `SELECT email FROM loyalty_members` should return `***`.

## Preview locally, no workspace

```bash
pip install pandas numpy scikit-learn pyarrow streamlit altair
python local_run.py                      # builds the same tables into .local_data/ in ~15s
NBO_LOCAL_DATA=.local_data streamlit run app/app.py
```

`src/nbo_lib.py` holds the simulation, features, model, and gold logic, so the local preview and the notebooks run the same code.

## Numbers the data is built to produce

25,000 members, seed 711. Step 3 prints the actual values.

| Metric | Target |
| --- | --- |
| Monthly discount spend | ~$2.0K Jan–Mar → ~$8.3K Apr–Sep (about 3×) |
| Monthly incremental margin | ~+$500 Jan–Mar → ~−$2.3K Apr–Sep |
| Coffee + Croissant redemption rate, Apr–Sep | ~38% |
| Coffee + Croissant redemptions that would happen anyway | ~67% |
| Coffee + Croissant net margin per send | all eligible ~−$1.1K, propensity-ranked ~−$1.5K, uplift-targeted ~+$700 |
| Measured lift, Persuadable vs Sure Thing (Coffee + Croissant) | ~+22 pts vs ~0 pts |
| Late-Night Energy $1 Off | No audience pays back → retire or redesign |

Dollar values scale linearly with members. Raise the `members` variable for bigger numbers; 100,000 takes roughly four times as long.
