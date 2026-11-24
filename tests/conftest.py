"""Shared fixtures: run the same pipeline the build job runs, small and in pandas, and write the
tables the app reads to a temp folder (what local_run.py does)."""

import os
import pickle
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import nbo_lib  # noqa: E402

MEMBERS = 2000


@pytest.fixture(scope="session")
def pipeline():
    raw, gold = nbo_lib.run_all(MEMBERS)
    train_f, score_f = nbo_lib.feature_windows(raw["pos_baskets"], raw["loyalty_members"])
    models = nbo_lib.train_uplift(raw["offer_history"], train_f)
    learners = {pid: {"treated": m["treated"], "control": m["control"]} for pid, m in models.items()}
    return {"raw": raw, "gold": gold, "member_features": score_f, "learners": learners}


def _sql_tables():
    """Tables created with SQL DDL in the notebooks (not from a DataFrame), as {name: [columns]}."""
    import sqlglot
    from sqlglot import exp

    out = {}
    for nb in (ROOT / "src").glob("*.py"):
        for m in re.finditer(r'"""\s*(CREATE TABLE IF NOT EXISTS .*?\))\s*\n\s*COMMENT', nb.read_text(), re.S):
            ddl = m.group(1).replace("{fq}.", "")
            tree = sqlglot.parse_one(ddl, read="databricks")
            name = tree.find(exp.Table).name
            out[name] = [c.name for c in tree.find_all(exp.ColumnDef)]
    return out


@pytest.fixture(scope="session")
def table_schemas(pipeline):
    """Column names of every table the build job writes, keyed by table name."""
    frames = {**pipeline["raw"], **pipeline["gold"], "member_features": pipeline["member_features"]}
    schemas = {name: list(df.columns) for name, df in frames.items()}
    schemas.update(_sql_tables())
    return schemas


@pytest.fixture(scope="session")
def local_data(pipeline, tmp_path_factory):
    out = tmp_path_factory.mktemp("local_data")
    raw, gold = pipeline["raw"], pipeline["gold"]
    with open(out / "uplift_learners.pkl", "wb") as fh:
        pickle.dump(pipeline["learners"], fh)
    pipeline["member_features"].to_parquet(out / "member_features.parquet", index=False)
    for name, df in {"promotions": raw["promotions"], "stores": raw["stores"],
                     "instore_events": raw["instore_events"], **gold}.items():
        df.to_parquet(out / f"{name}.parquet", index=False)
    tables = {"promotions": raw["promotions"], "stores": raw["stores"], **gold}
    nbo_lib.recommend_from_tables(tables, nbo_lib.DEFAULT_ASSUMPTIONS).to_csv(out / "agent_proposals.csv",
                                                                              index=False)
    return out
