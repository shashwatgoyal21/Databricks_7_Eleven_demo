# Real-Time Next Best Offer: The Right Offer While the Shopper Is Still in the Store

> **What this is.** While a shopper is in the store, the system picks the promotion most likely to get that person to add to their basket and sends it to them right then. A data and AI engineering audience also fits that use case. They care about the hard parts: streaming in-store signals, serving features with low latency, scoring models in milliseconds and governing all of it on Databricks.

All shoppers, stores, and numbers in this demo are fictional. The build kit is in this folder; see `README.md`.

## The Story

| | |
| --- | --- |
| **Company** | A convenience retailer: 120 stores across Texas, California, Florida, and the Northeast, 25,000 loyalty shoppers in the pilot |
| **Audience** | VP of Data Engineering, Head of Data Engineering, VP of AI Engineering |
| **Moment** | A shopper who shares location with the retailer's app walks into a store. The app already sees this. |
| **What has to happen** | Within a second, decide which of five promotions (or none) will make this person add to their basket, and get it onto their phone and the pin-pad before they reach the counter |
| **Why it is hard** | The check-in has to stream in, the shopper's features have to be read in milliseconds, five uplift models have to be scored, live rules applied, and every decision logged and governed |
| **How it works** | The retailer's app makes one API call to a Databricks Model Serving endpoint. Databricks returns the offer and the push text. The retailer's existing push tool delivers it. Nothing in their mobile or push stack is replaced. |
| **Proof** | A 10% holdout on every decision. Shoppers the model calls Persuadable show about **+22 pts** measured lift; shoppers it calls Sure Thing show about **0**. Versus the static rules used today, that is about **$44K a year** on the pilot base, scaling with shoppers. |

---

## Overview

The live day is **2026-09-30**. About **8,300 check-ins** arrive across 120 stores. Each one is a shopper's loyalty ID, a store, and a time, plus the first item scanned and days since the last visit when the store knows them.

The decision path, the same code everywhere it runs:

1. **Check-in.** The retailer's app sees the shopper enter the store and calls the `nbo-decision` endpoint with `member_id`, `store_id`, and `event_ts`.
2. **Features.** The endpoint reads the shopper's features (visit mix, category habits, recency) and the store's inventory from a Lakebase online store, kept in sync with Unity Catalog.
3. **Score.** Two models per promotion estimate the chance of a purchase with and without the offer. The difference is the uplift.
4. **Live rules.** Is it the right time of day? Did they already scan the item? Does this store have fresh bakery? Are they in the win-back window?
5. **Pick one.** The offer with the highest expected net margin among those that move this shopper. If none pays back, no offer.
6. **Hold out.** 1 in 10 check-ins gets no offer, so the effect is always measured.
7. **Respond.** Offer, push title, push text, and reason go back to the caller. The request and response land in an inference table.

Only about **18%** of check-ins get an offer. The other 80% are suppressed on purpose, because no offer would change what that shopper buys at that moment.

---

## Key Numbers

| Metric | Value |
| --- | --- |
| Shoppers / stores / promotions | 25,000 / 120 / 5 |
| POS baskets for training | ~3.3M, Oct 2025 to Sep 2026 |
| Live-day check-ins | ~8,300 (~70 per store) |
| Check-ins that get an offer | ~18% |
| Check-ins suppressed (no offer moves the shopper or fits the moment) | ~80% |
| Holdout | 10% of check-ins |
| Request the retailer's app sends | 3 required fields |
| Round trip from the app, local preview | ~50 ms |
| Measured lift, Persuadable vs Sure Thing | ~+22 pts vs ~0 pts |
| Static rules since Apr 1, monthly incremental margin | ~+$500 to ~-$2.3K |
| Coffee + Croissant redemptions that would happen anyway under static rules | ~67% |
| Annual gain, model vs static rules | ~$44K on the pilot base |

---

## Demo Walkthrough

**Frame:** *"A shopper walks into a store. In the next second we need to decide which offer, if any, gets them to buy more, and get it to their phone. Here is the whole path on Databricks, end to end."*

### Act 1: A shopper walks in (2 min)

Open the **Databricks App**, tab **In-Store Live**. The store is already picked. The phone shows the one-time "Allow 7-Eleven to use your location?" prompt.

Click **Next shopper walks in**. A commuter scans a coffee at 6:31am. The app sends the check-in to the endpoint, and the phone shows *"Your coffee is better with a croissant"* with the round trip in milliseconds. The pin-pad shows the same offer.

Click **Play 15 minutes**. Check-ins stream in. Most get no offer. The KPI row shows check-ins, offers sent, suppressed, held out, and p50/p95 round trip.

If **Send real pushes** is on, the notification arrives on your own phone through the push service, the same way it would through the retailer's Braze, Airship, or OneSignal account.

### Act 2: Why that offer (2 min)

Open **Decision Trace**. Pick *"Coffee scanned, gets the croissant offer"*. Show the check-in JSON, the shopper's features, and the table of all five promotions with their with-offer and without-offer scores, uplift, expected margin, and which live rules passed.

Switch to *"Coffee scanned, already buys pastries: no offer"*. Same moment, same scan, but this shopper adds a pastry most mornings anyway. The model calls them a Sure Thing. No discount is given away.

Show the request and response JSON. Point out that the request is three fields.

### Act 3: How it runs (2 min)

Open **Under the Hood**. Walk the architecture:

- Check-ins land through **Zerobus** (or Kafka) into the `instore_events` Delta table.
- **Lakeflow** jobs keep `member_features` fresh, and it is published to a **Lakebase** online store.
- The **Model Serving** endpoint `nbo-decision` serves one pyfunc: feature lookup, uplift scoring, live rules, holdout.
- **AI Gateway** logs every request and response to the `nbo_decision_payload` inference table.
- **Unity Catalog** governs all of it: lineage, row filters by region, PII masks, and grants.

Show the latency budget table and the live row counts.

### Act 4: Does it work? (1 min)

Open **Does the Model Work?**. The holdout shows Persuadables at about +22 pts and Sure Things at about 0. The trend chart shows what static rules did from April 1: discount spend up, incremental margin negative. The model gets about $44K a year back on the pilot base.

Optional: open the **AI/BI dashboard** page "Real-time decisions" (decisions by hour, why no offer, endpoint latency from the inference table), and ask **Genie** *"Why did most check-ins get no offer?"*

### Closing

*"The retailer's app makes one call. Databricks decides in milliseconds, using fresh features and a governed model, and their existing push stack delivers it. Every decision is logged, held out, and measured, so you can prove what it earns."*

---

## Products Showcased

| Product | Mode | What it does in this demo |
| --- | --- | --- |
| **Model Serving** | Build | `nbo-decision` endpoint: one check-in in, one offer out, in milliseconds |
| **Feature Engineering + Lakebase online store** | Build | `member_features` and `stores` served by key with continuous sync |
| **MLflow + Unity Catalog model registry** | Build | Uplift learners and the `nbo_decision_service` pyfunc, `@prod` alias |
| **AI Gateway inference tables** | Build | Every request and response logged to `nbo_decision_payload` |
| **Structured Streaming** | Build | `05_stream_decisions`: the same decision path over the check-in stream, written to `offer_decisions` |
| **Lakeflow Jobs** | Build | Data, features, training, streaming, endpoint, and governance in one job |
| **Unity Catalog** | Build | Row filter by region, PII mask, metric view `metrics_promotions`, lineage, grants |
| **Databricks Apps** | Build | Live console: walk-in simulator, real push, decision trace, architecture |
| **AI/BI Dashboard and Genie** | Build | Decisions, suppression reasons, latency, and lift, on the same governed data |
| **Declarative Automation Bundles** | Build | Deploys the whole thing to a new workspace in one command |
| **Zerobus** | Talk track | Direct ingest of check-ins from the app backend into Delta |
