"""The model was never told the date. Asked in September 2026 who won "the last"
Champions League final, it searched and still said 2024; it said the iPhone 17
"hasn't been released yet"."""
from datetime import datetime
from zoneinfo import ZoneInfo

import core.brain as brain_mod
from core.brain import Brain


def test_the_prompt_says_the_date_and_time_in_cairo(monkeypatch):
    monkeypatch.setattr(brain_mod, "_cairo_now",
                        lambda: datetime(2026, 9, 15, 20, 5, tzinfo=ZoneInfo("Africa/Cairo")))
    text = Brain(profile={})._build_system()[-1]["text"]
    assert "Tuesday, 15 September 2026" in text
    assert "08:05 PM" in text


def test_the_date_stays_out_of_the_cached_prefix():
    blocks = Brain(profile={})._build_system()
    assert "Right now it is" not in blocks[0]["text"]
    assert "cache_control" not in blocks[-1]
