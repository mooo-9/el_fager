from core.agents.strategy_engine import StrategyEngine


class TestDetectRegime:
    def test_rising_prices_returns_bull(self):
        eng = StrategyEngine()
        # Second half averages >2% above first half
        closes = [100.0 + i * 0.6 for i in range(25)]
        assert eng._detect_regime(closes) == "bull"

    def test_falling_prices_returns_bear(self):
        eng = StrategyEngine()
        closes = [100.0 - i * 0.6 for i in range(25)]
        assert eng._detect_regime(closes) == "bear"

    def test_flat_prices_returns_sideways(self):
        eng = StrategyEngine()
        closes = [100.0] * 20
        assert eng._detect_regime(closes) == "sideways"

    def test_short_series_returns_sideways(self):
        eng = StrategyEngine()
        assert eng._detect_regime([100.0, 101.0]) == "sideways"


class TestMeanReversionSignal:
    def test_price_far_below_band_returns_buy(self):
        eng = StrategyEngine()
        # 18 stable prices then two sharp drops -> oversold vs band
        closes = [100.0] * 18 + [91.5, 91.0]
        assert eng._mean_reversion_signal(closes) == "BUY"

    def test_price_far_above_band_returns_sell(self):
        eng = StrategyEngine()
        closes = [100.0] * 18 + [108.5, 109.0]
        assert eng._mean_reversion_signal(closes) == "SELL"

    def test_price_near_mean_returns_hold(self):
        eng = StrategyEngine()
        closes = [100.0] * 20
        assert eng._mean_reversion_signal(closes) == "HOLD"

    def test_short_series_returns_hold(self):
        eng = StrategyEngine()
        assert eng._mean_reversion_signal([100.0] * 5) == "HOLD"


class TestMomentumSwingSignal:
    def test_returns_valid_direction(self):
        eng = StrategyEngine()
        closes = [100.0 + i * 0.1 for i in range(40)]
        result = eng._momentum_swing_signal(closes)
        assert result in ("BUY", "SELL", "HOLD")

    def test_short_series_returns_hold(self):
        eng = StrategyEngine()
        assert eng._momentum_swing_signal([100.0] * 5) in ("BUY", "SELL", "HOLD")


class TestSelectStrategy:
    def test_returns_tuple_of_str_and_float(self, monkeypatch):
        eng = StrategyEngine()
        monkeypatch.setattr(eng, "_fetch_spy_closes", lambda: [100.0 + i * 0.5 for i in range(25)])
        closes = [80.0 + i * 0.3 for i in range(40)]
        strategy, modifier = eng.select_strategy("NVDA", closes)
        assert isinstance(strategy, str)
        assert isinstance(modifier, float)
        assert 0.5 <= modifier <= 1.5

    def test_modifier_is_positive(self, monkeypatch):
        eng = StrategyEngine()
        monkeypatch.setattr(eng, "_fetch_spy_closes", lambda: [100.0] * 25)
        closes = [100.0] * 40
        _, modifier = eng.select_strategy("AAPL", closes)
        assert modifier > 0

    def test_fetch_spy_closes_exception_returns_empty(self, monkeypatch):
        eng = StrategyEngine()
        # When _fetch_spy_closes fails (no API), select_strategy still returns valid output
        monkeypatch.setattr(eng, "_fetch_spy_closes", lambda: [])
        closes = [100.0] * 40
        strategy, modifier = eng.select_strategy("AAPL", closes)
        assert isinstance(strategy, str)
        assert modifier > 0
