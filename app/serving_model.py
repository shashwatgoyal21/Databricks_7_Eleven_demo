"""MLflow pyfunc for the real-time decision endpoint.

Request: one row per in-store check-in (member_id, store, daypart, first item scanned, days since the
previous visit, ...). The endpoint looks up the shopper's features from the online feature store by
member_id, scores the uplift model for every promotion, applies the live rules, and returns one offer
or no offer. Same code as the app and the streaming job (nbo_decision.py).
"""

import pickle

import mlflow
import pandas as pd
from mlflow.pyfunc import PythonModel

import nbo_decision as nd

RESPONSE_COLS = ["event_id", "member_id", "store_id", "decision", "promotion_id", "offer_message", "channel",
                 "push_title", "p_without_offer", "p_with_offer", "uplift", "expected_net_margin", "holdout",
                 "reason"]


class NBODecisionService(PythonModel):
    def load_context(self, context):
        with open(context.artifacts["learners"], "rb") as fh:
            self.models = pickle.load(fh)

    def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
        out = nd.score_and_decide(model_input, self.models)
        out["promotion_id"] = out.promotion_id.fillna("")
        out[["offer_message", "channel"]] = out[["offer_message", "channel"]].fillna("")
        served = out.decision == "Offer served"
        out["push_title"] = out.promotion_id.map(nd.PUSH_TITLE).where(served, "").fillna("")
        return out[RESPONSE_COLS].fillna({"p_without_offer": 0.0, "p_with_offer": 0.0, "uplift": 0.0,
                                         "expected_net_margin": 0.0})
