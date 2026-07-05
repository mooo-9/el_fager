"""Unit tests for core/telemetry.py — API usage logging and cost metering."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import core.telemetry as tel


@pytest.fixture(autouse=True)
def isolated_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tel, "_TELEMETRY_DIR", tmp_path / "telemetry")
    yield tmp_path


def _usage(inp=1000, out=500, cache_w=0, cache_r=0):
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_creation_input_tokens=cache_w,
        cache_read_input_tokens=cache_r,
    )


class TestCost:
    def test_opus_pricing(self):
        # 1M in @ $5 + 1M out @ $25
        cost = tel.estimate_cost("claude-opus-4-8", _usage(1_000_000, 1_000_000))
        assert cost == pytest.approx(30.0)

    def test_haiku_pricing(self):
        cost = tel.estimate_cost("claude-haiku-4-5", _usage(1_000_000, 1_000_000))
        assert cost == pytest.approx(6.0)

    def test_cache_read_is_cheap(self):
        # 1M cache-read @ 0.1x input price ($5) = $0.50
        cost = tel.estimate_cost("claude-opus-4-8", _usage(0, 0, 0, 1_000_000))
        assert cost == pytest.approx(0.5)

    def test_cache_write_premium(self):
        # 1M cache-write @ 1.25x input price ($5) = $6.25
        cost = tel.estimate_cost("claude-opus-4-8", _usage(0, 0, 1_000_000, 0))
        assert cost == pytest.approx(6.25)

    def test_unknown_model_uses_fallback(self):
        cost = tel.estimate_cost("claude-mystery-9", _usage(1_000_000, 0))
        assert cost > 0

    def test_missing_cache_fields_tolerated(self):
        usage = SimpleNamespace(input_tokens=100, output_tokens=50)
        assert tel.estimate_cost("claude-opus-4-8", usage) > 0


class TestRecord:
    def test_record_appends_jsonl(self, isolated_dir):
        tel.record_api_usage("chat", "claude-opus-4-8", _usage(), 1234.5,
                             tools_used=["web_search"])
        day = datetime.now().strftime("%Y-%m-%d")
        lines = (isolated_dir / "telemetry" / f"{day}.jsonl").read_text(
            encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["source"] == "chat"
        assert entry["model"] == "claude-opus-4-8"
        assert entry["input_tokens"] == 1000
        assert entry["output_tokens"] == 500
        assert entry["latency_ms"] == 1234.5
        assert entry["tools_used"] == ["web_search"]
        assert entry["cost_usd"] > 0

    def test_record_never_raises(self):
        # Garbage usage object must not break the assistant
        tel.record_api_usage("chat", "claude-opus-4-8", object(), 1.0)


class TestSummarize:
    def _write_day(self, base, days_ago, entries):
        d = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        path = base / "telemetry" / f"{d}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(e) for e in entries),
                        encoding="utf-8")

    def test_summarize_totals(self, isolated_dir):
        self._write_day(isolated_dir, 0, [
            {"source": "chat", "model": "m", "cost_usd": 0.10,
             "input_tokens": 100, "output_tokens": 50, "latency_ms": 1000},
            {"source": "screenshot", "model": "m", "cost_usd": 0.05,
             "input_tokens": 60, "output_tokens": 20, "latency_ms": 3000},
        ])
        self._write_day(isolated_dir, 1, [
            {"source": "chat", "model": "m", "cost_usd": 0.20,
             "input_tokens": 200, "output_tokens": 90, "latency_ms": 2000},
        ])
        s = tel.summarize(days=7)
        assert s["requests"] == 3
        assert s["cost_usd"] == pytest.approx(0.35)
        assert s["by_source"]["chat"]["requests"] == 2
        assert s["by_source"]["chat"]["cost_usd"] == pytest.approx(0.30)
        assert s["avg_latency_ms"] == pytest.approx(2000)

    def test_summarize_respects_window(self, isolated_dir):
        self._write_day(isolated_dir, 0, [{"source": "chat", "model": "m",
                                           "cost_usd": 0.10}])
        self._write_day(isolated_dir, 5, [{"source": "chat", "model": "m",
                                           "cost_usd": 9.99}])
        s = tel.summarize(days=1)
        assert s["cost_usd"] == pytest.approx(0.10)

    def test_summarize_empty(self, isolated_dir):
        s = tel.summarize(days=7)
        assert s["requests"] == 0
        assert s["cost_usd"] == 0

    def test_cost_today_helper(self, isolated_dir):
        self._write_day(isolated_dir, 0, [{"source": "chat", "model": "m",
                                           "cost_usd": 1.25}])
        assert tel.cost_today() == pytest.approx(1.25)
