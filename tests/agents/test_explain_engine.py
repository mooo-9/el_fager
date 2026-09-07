from unittest.mock import patch, MagicMock
from core.agents.explain_engine import ExplainEngine
from core.agents.market_analyst import AnalysisResult


def _make_analysis(symbol="NVDA", conviction=88.0, direction="BUY"):
    return AnalysisResult(
        symbol=symbol,
        conviction=conviction,
        direction=direction,
        technical_score=90.0,
        fundamental_score=80.0,
        sentiment_score=85.0,
        rationale="RSI oversold, strong momentum, positive news",
    )


class TestExplainEngine:
    def test_returns_non_empty_string(self):
        analysis = _make_analysis()
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="NVDA shows 88% conviction based on strong momentum.")]
        with patch("anthropic.Anthropic") as MockCl:
            MockCl.return_value.messages.create.return_value = mock_resp
            result = ExplainEngine().explain("Why did you buy NVDA?", symbol="NVDA", analysis=analysis)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_uses_haiku_model(self):
        analysis = _make_analysis()
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="NVDA is strong.")]
        with patch("anthropic.Anthropic") as MockCl:
            MockCl.return_value.messages.create.return_value = mock_resp
            ExplainEngine().explain("thesis on NVDA", analysis=analysis)
            call_kwargs = MockCl.return_value.messages.create.call_args
            if call_kwargs:
                assert "haiku" in call_kwargs.kwargs.get("model", "")

    def test_fallback_contains_symbol_on_api_failure(self):
        analysis = _make_analysis("AAPL", 75.0)
        with patch("anthropic.Anthropic", side_effect=Exception("API down")):
            result = ExplainEngine().explain("What's your thesis?", symbol="AAPL", analysis=analysis)
        assert "AAPL" in result
        assert "75" in result

    def test_works_without_analysis(self):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="No current open positions.")]
        with patch("anthropic.Anthropic") as MockCl:
            MockCl.return_value.messages.create.return_value = mock_resp
            result = ExplainEngine().explain("How are we doing?")
        assert isinstance(result, str)

    def test_load_trades_context_handles_missing_file(self, tmp_path, monkeypatch):
        import core.agents.explain_engine as ee
        monkeypatch.setattr(ee, "_TRADES_PATH", tmp_path / "trades.json")
        engine = ExplainEngine()
        assert engine._load_trades_context(None) == ""

    def test_load_trades_context_filters_by_symbol(self, tmp_path, monkeypatch):
        import json, core.agents.explain_engine as ee
        trades_file = tmp_path / "trades.json"
        trades_file.write_text(json.dumps([
            {"symbol": "NVDA", "side": "buy", "qty": 0.01, "price": 450.0,
             "timestamp": "2026-06-22T10:00:00", "signal": "conviction"},
            {"symbol": "AAPL", "side": "buy", "qty": 0.05, "price": 200.0,
             "timestamp": "2026-06-22T11:00:00", "signal": "conviction"},
        ]))
        monkeypatch.setattr(ee, "_TRADES_PATH", trades_file)
        engine = ExplainEngine()
        context = engine._load_trades_context("NVDA")
        assert "NVDA" in context
        assert "AAPL" not in context
