# Real-Time NBO app: AppKit design

Design for rebuilding `nbo-demo/app` (today Streamlit) as a custom-code Databricks App on AppKit (Node/TypeScript/React). Same four screens, same tables, same `nbo-decision` endpoint.

## Direction

- **What this is:** While a shopper is in the store, the system picks the promotion most likely to get that person to add to their basket and sends it to them right then.
- **Audience:** VP of Data Engineering, Head of Data Engineering, VP of AI Engineering. They care about the hard parts: streaming in-store signals, serving features with low latency, scoring models in milliseconds, and governing all of it on Databricks.
- **Frame:** Presented live on a call. The app is a window onto a working decision path, not a business-user tool. Every screen shows what the system did and how fast, with the payloads visible.
- **Genre:** Operational (live feed) on screen 1, explanatory (trace, architecture, evidence) on screens 2 to 4.

## Screens

| # | Screen | Message | Main components | Data |
| --- | --- | --- | --- | --- |
| 1 | In-Store Live | A shopper shares location, walks in, and gets one offer in milliseconds, or none | Store `Select`; `Button` "Next shopper walks in", "Play 15 minutes"; phone and pin-pad mock (custom component); 5 KPI `Card`s (check-ins, offers pushed, suppressed, held out, p50/p95 round trip); `DataTable` decision stream | `instore_events` by store; POST to `nbo-decision` per check-in via a server route; append to `live_decision_log` |
| 2 | Decision Trace | One check-in end to end | Event `CodeBlock` (JSON); feature `Card`; offer mock; scored-promotions `DataTable` with live-rule pass/fail; request and response `CodeBlock`s | `featured_events`, `member_offer_scores`, `member_profile`, endpoint response |
| 3 | Under the Hood | Streaming ingest, online features, ms scoring, governance | Architecture diagram (static SVG); latency budget `DataTable`; tables `DataTable` with row counts | `information_schema`, `COUNT(*)` per table |
| 4 | Does the Model Work? | Holdout proves Persuadables move and Sure Things don't; static rules lose money | Small-multiple bar chart by tier; spend vs margin line with the 1 Apr reference line; per-promotion `DataTable` | `tier_backtest`, `promo_monthly`, `promo_portfolio` |

## Server routes

| Route | Does | Runs as |
| --- | --- | --- |
| `POST /api/checkin` | Forwards one check-in to the `nbo-decision` endpoint, returns the response and measured round trip | App service principal (`CAN_QUERY` on the endpoint) |
| `POST /api/decision-log` | Inserts decisions into `live_decision_log` | App service principal (`MODIFY`) |
| `GET` queries | `*.obo.sql` so `nbo_region_filter` and `nbo_pii_mask` apply to the viewer | Signed-in user (`sql` scope) |

## Notation

- One meaning per color: green = offer pushed / pays back, grey = no offer or baseline, orange = discount spend, red = loses money.
- Latency always says what it measures: round trip from the app, or server-side `execution_duration_ms` from the inference table.
- Rates in %, lift in pts, money with sign and period (per month, per year).
- Names show `***` when the viewer lacks `nbo_pii_readers`.

## States

- Endpoint not ready or not granted: banner with the error, decisions fall back to the in-app copy of `nbo_decision.py`, labelled as fallback.
- Store with no check-ins left: buttons disabled, "End of day" in the clock KPI.
- Empty decision stream: share-location permission prompt and one line explaining the trigger.
