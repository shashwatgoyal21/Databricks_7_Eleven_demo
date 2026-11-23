"""Run the whole Streamlit app against locally built tables and fail on any exception on any tab."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app" / "app.py"


@pytest.fixture()
def app(local_data, monkeypatch):
    monkeypatch.setenv("NBO_LOCAL_DATA", str(local_data))
    monkeypatch.setenv("NBO_ENDPOINT", "")
    monkeypatch.setenv("GENIE_SPACE_ID", "")
    import importlib

    import data
    importlib.reload(data)
    at = AppTest.from_file(str(APP), default_timeout=120)
    return at.run()


def test_app_renders_without_errors(app):
    assert not app.exception, [e.value for e in app.exception]


def test_app_has_no_emojis(app):
    import re
    text = APP.read_text()
    emoji = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
    assert not emoji.findall(text), set(emoji.findall(text))


def test_buttons_do_not_raise(app):
    for b in list(app.button)[:6]:
        b.click().run()
        assert not app.exception, (b.label, [e.value for e in app.exception])
