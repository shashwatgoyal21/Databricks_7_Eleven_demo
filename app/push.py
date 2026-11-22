"""Send the offer through whatever push stack the retailer already runs.

The decision endpoint returns the offer and the push text. Something then has to deliver it to the phone.
In production that is usually the retailer's own app backend or their customer-engagement platform. This
module is a thin adapter so the demo (and a production dispatcher) can hand the same payload to any of them:

    ntfy      demo only: a real notification on a phone running the free ntfy app
    webhook   POST the APNs-shaped JSON to any URL (their app backend, a push gateway, a test receiver)
    braze     Braze /messages/send to the shopper's external_id
    airship   Airship /api/push to the shopper's named_user
    onesignal OneSignal /notifications to the shopper's external_id

Pick one with NBO_PUSH_PROVIDER and NBO_PUSH_URL (plus NBO_PUSH_API_KEY / NBO_PUSH_APP_ID where needed;
keep keys in a Databricks secret and map them in app.yaml). No code changes to switch.
"""

import json
import os
import time
import urllib.request
from urllib.parse import urlparse

PROVIDER = os.getenv("NBO_PUSH_PROVIDER", "").strip().lower()
URL = os.getenv("NBO_PUSH_URL", "").strip()
API_KEY = os.getenv("NBO_PUSH_API_KEY", "").strip()
APP_ID = os.getenv("NBO_PUSH_APP_ID", "").strip()

if not PROVIDER and URL:
    PROVIDER = "ntfy" if "ntfy" in URL else "webhook"


def configured():
    return bool(PROVIDER and (URL or PROVIDER == "airship" or PROVIDER == "onesignal"))


def label():
    if not configured():
        return "not configured (set NBO_PUSH_PROVIDER and NBO_PUSH_URL)"
    if PROVIDER == "ntfy":
        return f"ntfy topic {URL.rstrip('/').rsplit('/', 1)[-1]}"
    return PROVIDER


def _request(provider, payload, member_id):
    """Build (url, headers, body) for one provider from the APNs-shaped payload."""
    alert = payload["aps"]["alert"]
    title, body = alert["title"], alert["body"]
    extra = {"offer_id": payload["offer_id"], "event_id": payload["event_id"], "store_id": payload["store_id"]}
    uid = str(member_id)
    if provider == "ntfy":
        u = urlparse(URL)
        return (f"{u.scheme}://{u.netloc}", {},
                {"topic": u.path.strip("/"), "title": title, "message": body, "tags": ["convenience_store"],
                 "priority": 4})
    if provider == "braze":
        return (f"{URL.rstrip('/')}/messages/send", {"Authorization": f"Bearer {API_KEY}"},
                {"external_user_ids": [uid],
                 "messages": {"apple_push": {"alert": {"title": title, "body": body}, "extra": extra},
                              "android_push": {"title": title, "alert": body, "extra": extra}}})
    if provider == "airship":
        return (URL or "https://go.urbanairship.com/api/push",
                {"Authorization": f"Bearer {API_KEY}", "Accept": "application/vnd.urbanairship+json; version=3"},
                {"audience": {"named_user": uid}, "device_types": ["ios", "android"],
                 "notification": {"alert": body, "ios": {"title": title, "extra": extra},
                                  "android": {"title": title, "extra": extra}}})
    if provider == "onesignal":
        return (URL or "https://api.onesignal.com/notifications", {"Authorization": f"Key {API_KEY}"},
                {"app_id": APP_ID, "target_channel": "push", "include_aliases": {"external_id": [uid]},
                 "headings": {"en": title}, "contents": {"en": body}, "data": extra})
    # webhook: the APNs payload as-is, plus who it is for
    return URL, {}, {**payload, "member_id": member_id}


def send(payload, member_id):
    """Deliver one push. Returns (status, ms). Never raises."""
    if payload is None or not configured():
        return "not sent", 0.0
    url, headers, body = _request(PROVIDER, payload, member_id)
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            status = f"sent via {PROVIDER} ({r.status})"
    except Exception as e:
        status = f"{PROVIDER} failed: {str(e)[:80]}"
    return status, (time.perf_counter() - t0) * 1000
