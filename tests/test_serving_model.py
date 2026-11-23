"""The decision endpoint's model: same request shape as 06_serve_decisions builds, a response with the
documented columns, and a signature Unity Catalog will accept (inputs and outputs)."""

import json

import mlflow
import pandas as pd
import pytest
from mlflow.models import infer_signature

import nbo_decision as nd
from serving_model import RESPONSE_COLS, NBODecisionService

STORE_FEATURES = ["has_fresh_bakery", "region", "city"]


@pytest.fixture(scope="module")
def request_frame(pipeline):
    """What the endpoint sees after feature lookup: the check-in plus member and store features."""
    raw = pipeline["raw"]
    feats = pipeline["member_features"][["member_id"] + nd.MODEL_FEATURES + ["marketing_opt_in", "days_since_last_visit"]]
    stores = raw["stores"][["store_id"] + STORE_FEATURES]
    ev = raw["instore_events"][nd.CHECKIN_FIELDS].head(50).copy()
    ev["event_ts"] = ev.event_ts.astype(str)
    return ev.merge(feats, on="member_id").merge(stores, on="store_id")


@pytest.fixture(scope="module")
def service(pipeline, tmp_path_factory):
    import pickle
    path = tmp_path_factory.mktemp("artifacts") / "uplift_learners.pkl"
    with open(path, "wb") as fh:
        pickle.dump(pipeline["learners"], fh)

    class _Ctx:
        artifacts = {"learners": str(path)}

    svc = NBODecisionService()
    svc.load_context(_Ctx())
    return svc, str(path)


def test_response_has_documented_columns(service, request_frame):
    out = service[0].predict(None, request_frame)
    assert list(out.columns) == RESPONSE_COLS
    assert len(out) == len(request_frame)


def test_response_has_no_missing_values_and_is_json_serializable(service, request_frame):
    out = service[0].predict(None, request_frame)
    assert not out.isna().any().any(), out.isna().sum()[lambda s: s > 0]
    json.dumps(out.to_dict("records"), default=str)


def test_decisions_are_known_values(service, request_frame):
    out = service[0].predict(None, request_frame)
    picked = out.decision.isin(["Offer served", "Holdout (no offer shown)"])
    assert out.loc[picked, "promotion_id"].isin(nd.PROMO_ECONOMICS).all()
    assert (out.loc[~picked, "promotion_id"] == "").all()
    assert (out.loc[out.decision != "Offer served", "push_title"] == "").all()


def test_signature_has_inputs_and_outputs(service, request_frame):
    """Unity Catalog rejects a model whose signature has only inputs (the first serving failure)."""
    out = service[0].predict(None, request_frame)
    sig = infer_signature(request_frame, out)
    assert sig.inputs is not None and sig.outputs is not None


def test_model_saves_and_reloads_like_serving(service, request_frame, tmp_path):
    """Log the pyfunc the way serving loads it and score through the loaded copy."""
    from pathlib import Path
    app = Path(nd.__file__).parent
    out = service[0].predict(None, request_frame)
    mlflow.pyfunc.save_model(
        path=str(tmp_path / "model"), python_model=NBODecisionService(),
        artifacts={"learners": service[1]},
        code_paths=[str(app / "nbo_decision.py"), str(app / "serving_model.py")],
        signature=infer_signature(request_frame, out),
    )
    loaded = mlflow.pyfunc.load_model(str(tmp_path / "model"))
    assert loaded.metadata.signature.outputs is not None
    again = loaded.predict(request_frame)
    assert list(again.columns) == RESPONSE_COLS
