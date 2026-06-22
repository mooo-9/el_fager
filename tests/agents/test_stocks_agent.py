import json
from unittest.mock import patch, MagicMock
import core.agents.stocks_agent as sa
from core.agents.stocks_agent import StocksAgent
from core.agents.market_analyst import AnalysisResult


def _analysis(symbol="NVDA", conviction=75.0, direction="BUY"):
    return AnalysisResult(symbol, conviction, direction, 80.0, 70.0, 75.0, "test rationale")


class TestParseSymbol:
    def test_recognizes_nvda_lowercase(self):
        assert StocksAgent()._parse_symbol("analyze nvda for me") == "NVDA"

    def test_recognizes_uppercase_ticker_in_sentence(self):
        assert StocksAgent()._parse_symbol("What do you think about MSFT?") == "MSFT"

    def test_returns_none_when_no_symbol(self):
        assert StocksAgent()._parse_symbol("how are we doing overall?") is None

    def test_prefers_known_symbol_list_over_random_uppercase(self):
        result = StocksAgent()._parse_symbol("analyze aapl vs RANDOMCORP")
        assert result == "AAPL"


class TestHandleControlCommand:
    def test_pause_sets_config_true(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({"auto_trade_paused": False}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)
        result = StocksAgent()._handle_control_command("pause trading")
        assert result is not None
        assert "paused" in result.lower()
        assert json.loads(config_file.read_text())["auto_trade_paused"] is True

    def test_resume_sets_config_false(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({"auto_trade_paused": True}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)
        result = StocksAgent()._handle_control_command("resume trading")
        assert result is not None
        assert json.loads(config_file.read_text())["auto_trade_paused"] is False

    def test_set_threshold_to_90(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({"auto_trade_threshold": 85}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)
        result = StocksAgent()._handle_control_command("set auto-trade threshold to 90%")
        assert result is not None
        assert json.loads(config_file.read_text())["auto_trade_threshold"] == 90

    def test_set_threshold_rejects_out_of_range(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)
        result = StocksAgent()._handle_control_command("set threshold to 110%")
        assert "must be between" in result.lower()

    def test_non_command_returns_none(self):
        assert StocksAgent()._handle_control_command("analyze NVDA") is None


class TestConvictionGating:
    def test_high_conviction_auto_executes(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({
            "auto_trade_threshold": 85,
            "auto_trade_paused": False,
            "conviction_delay_seconds": 60,
        }))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)

        mock_analyst = MagicMock()
        mock_analyst.analyze.return_value = _analysis(conviction=90.0)
        mock_analyst._fetch_ohlcv.return_value = ([100.0] * 40, [1_000_000] * 40)

        agent = StocksAgent()
        with patch("core.agents.market_analyst.MarketAnalyst", return_value=mock_analyst):
            with patch("core.agents.strategy_engine.StrategyEngine") as MockSE:
                MockSE.return_value.select_strategy.return_value = ("momentum_swing", 1.0)
                with patch.object(agent, "_place_trade", return_value="Bought 0.01 NVDA @ $450.00.") as mock_trade:
                    result = agent._analyze_and_decide("NVDA")
                    mock_trade.assert_called_once_with("NVDA")
        assert "auto-executing" in result.lower() or "auto-exec" in result.lower()

    def test_paused_skips_trade_even_at_high_conviction(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({"auto_trade_paused": True, "auto_trade_threshold": 85}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)

        mock_analyst = MagicMock()
        mock_analyst.analyze.return_value = _analysis(conviction=95.0)
        mock_analyst._fetch_ohlcv.return_value = ([100.0] * 40, [1_000_000] * 40)

        agent = StocksAgent()
        with patch("core.agents.market_analyst.MarketAnalyst", return_value=mock_analyst):
            with patch("core.agents.strategy_engine.StrategyEngine") as MockSE:
                MockSE.return_value.select_strategy.return_value = ("momentum_swing", 1.0)
                with patch.object(agent, "_place_trade") as mock_trade:
                    result = agent._analyze_and_decide("NVDA")
                    mock_trade.assert_not_called()
        assert "paused" in result.lower()

    def test_low_conviction_asks_confirmation(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({"auto_trade_threshold": 85, "auto_trade_paused": False}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)

        mock_analyst = MagicMock()
        mock_analyst.analyze.return_value = _analysis(conviction=45.0)
        mock_analyst._fetch_ohlcv.return_value = ([100.0] * 40, [1_000_000] * 40)

        agent = StocksAgent()
        with patch("core.agents.market_analyst.MarketAnalyst", return_value=mock_analyst):
            with patch("core.agents.strategy_engine.StrategyEngine") as MockSE:
                MockSE.return_value.select_strategy.return_value = ("no_signal", 1.0)
                with patch.object(agent, "_place_trade") as mock_trade:
                    result = agent._analyze_and_decide("NVDA")
                    mock_trade.assert_not_called()
        assert "below 60" in result or "confirm" in result.lower()

    def test_sell_direction_skips_buy(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({"auto_trade_threshold": 85, "auto_trade_paused": False}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)

        mock_analyst = MagicMock()
        mock_analyst.analyze.return_value = _analysis(conviction=90.0, direction="SELL")
        mock_analyst._fetch_ohlcv.return_value = ([100.0] * 40, [1_000_000] * 40)

        agent = StocksAgent()
        with patch("core.agents.market_analyst.MarketAnalyst", return_value=mock_analyst):
            with patch("core.agents.strategy_engine.StrategyEngine") as MockSE:
                MockSE.return_value.select_strategy.return_value = ("no_signal", 1.0)
                with patch.object(agent, "_place_trade") as mock_trade:
                    result = agent._analyze_and_decide("NVDA")
                    mock_trade.assert_not_called()
        assert "SELL" in result or "sell" in result.lower()


class TestBaseAgentContract:
    def test_name_is_stocks(self):
        assert StocksAgent().name == "stocks"

    def test_description_is_non_empty_string(self):
        assert isinstance(StocksAgent().description, str)
        assert len(StocksAgent().description) > 0
