"""Run the whole pipeline locally in pandas and write the gold tables to .local_data/.

The app reads .local_data/ when NBO_LOCAL_DATA is set, so the demo can be
previewed without a workspace:

    python local_run.py
    cd app && NBO_LOCAL_DATA=../.local_data uvicorn server:app --port 8000
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
import nbo_lib  # noqa: E402

members = int(sys.argv[1]) if len(sys.argv) > 1 else 25_000
out = Path(__file__).parent / ".local_data"
out.mkdir(exist_ok=True)

t0 = time.time()
raw, gold = nbo_lib.run_all(members)
# The learners and online features the decision endpoint uses, so the app can run it in-process
import pickle  # noqa: E402

train_f, score_f = nbo_lib.feature_windows(raw["pos_baskets"], raw["loyalty_members"])
models = nbo_lib.train_uplift(raw["offer_history"], train_f)
with open(out / "uplift_learners.pkl", "wb") as fh:
    pickle.dump({pid: {"treated": m["treated"], "control": m["control"]} for pid, m in models.items()}, fh)
score_f.to_parquet(out / "member_features.parquet", index=False)
print(f"Built in {time.time() - t0:.0f}s: {len(raw['pos_baskets']):,} baskets, "
      f"{len(raw['offer_history']):,} offer events")

# The tables the app reads
for name, df in {"promotions": raw["promotions"], "stores": raw["stores"],
                 "instore_events": raw["instore_events"], **gold}.items():
    df.to_parquet(out / f"{name}.parquet", index=False)

# The recommender's proposals and empty ledgers, as the build job writes them
tables = {"promotions": raw["promotions"], "stores": raw["stores"], **gold}
nbo_lib.recommend_from_tables(tables, nbo_lib.DEFAULT_ASSUMPTIONS).to_csv(out / "agent_proposals.csv", index=False)
for ledger in ("promotion_changes.csv", "agent_activity.csv"):
    (out / ledger).unlink(missing_ok=True)

nbo_lib.story_checks(nbo_lib.story_numbers(gold["promo_monthly"], gold["promo_portfolio"], gold["tier_backtest"]))
print()
print(gold["promo_portfolio"][["short_name", "eligible_members", "persuadable_members", "redemption_rate_apr_sep",
                               "measured_uplift_apr_sep", "blast_net_margin_per_send",
                               "targeted_net_margin_per_send", "status"]].round(3).to_string())
print()
print(gold["tier_backtest"].round(3).to_string())
print()
print(gold["offer_decisions"].decision.value_counts().to_string())
print()
print(gold["featured_events"].to_string())
