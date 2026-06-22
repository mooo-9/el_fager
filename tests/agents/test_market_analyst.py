from core.agents.market_analyst import MarketAnalyst, AnalysisResult


class TestAnalysisResult:
    def test_is_named_tuple_with_correct_fields(self):
        r = AnalysisResult(
            symbol="NVDA",
            conviction=75.0,
            direction="BUY",
            technical_score=80.0,
            fundamental_score=60.0,
            sentiment_score=70.0,
            rationale="test",
        )
        assert r.symbol == "NVDA"
        assert r.conviction == 75.0
        assert r.direction == "BUY"


class TestScoreTechnical:
    def test_oversold_series_scores_above_55(self):
        analyst = MarketAnalyst()
        closes = [100.0 - i * 0.8 for i in range(30)] + [72.0, 71.0, 70.0, 69.0, 68.0]
        volumes = [1_000_000] * len(closes)
        score, rationale = analyst._score_technical(closes, volumes)
        assert score >= 55, f"Oversold RSI series should score >= 55, got {score}"
        assert "RSI" in rationale

    def test_overbought_series_scores_below_55(self):
        analyst = MarketAnalyst()
        closes = [100.0 + i * 1.5 for i in range(35)]
        volumes = [1_000_000] * len(closes)
        score, rationale = analyst._score_technical(closes, volumes)
        assert score <= 55

    def test_returns_float_in_range_and_str(self):
        analyst = MarketAnalyst()
        closes = [100.0 + i * 0.1 for i in range(30)]
        volumes = [500_000] * len(closes)
        score, rationale = analyst._score_technical(closes, volumes)
        assert isinstance(score, float)
        assert isinstance(rationale, str)
        assert 0.0 <= score <= 100.0

    def test_short_series_returns_neutral_without_crash(self):
        analyst = MarketAnalyst()
        closes = [100.0] * 10
        volumes = [500_000] * 10
        score, rationale = analyst._score_technical(closes, volumes)
        assert 0.0 <= score <= 100.0


class TestScoreFundamental:
    def test_low_pe_and_strong_growth_scores_above_60(self, monkeypatch):
        import yfinance as yf
        fake_info = {"trailingPE": 12.0, "revenueGrowth": 0.25, "earningsQuarterlyGrowth": 0.30}
        monkeypatch.setattr(yf.Ticker, "info", property(lambda self: fake_info))
        analyst = MarketAnalyst()
        score, rationale = analyst._score_fundamental("AAPL")
        assert score >= 60, f"Low P/E + high growth should score >= 60, got {score}"
        assert "P/E" in rationale

    def test_high_pe_and_negative_growth_scores_below_50(self, monkeypatch):
        import yfinance as yf
        fake_info = {"trailingPE": 80.0, "revenueGrowth": -0.10, "earningsQuarterlyGrowth": -0.20}
        monkeypatch.setattr(yf.Ticker, "info", property(lambda self: fake_info))
        analyst = MarketAnalyst()
        score, rationale = analyst._score_fundamental("XYZ")
        assert score < 50

    def test_exception_returns_neutral(self, monkeypatch):
        import yfinance as yf
        def raise_error(self):
            raise RuntimeError("network error")
        monkeypatch.setattr(yf.Ticker, "info", property(raise_error))
        analyst = MarketAnalyst()
        score, rationale = analyst._score_fundamental("XYZ")
        assert score == 50.0


class TestScoreSentiment:
    def test_positive_news_scores_above_50(self, monkeypatch):
        monkeypatch.setattr(
            "tools.stocks_tool.get_stock_news",
            lambda symbol: "NVDA beats earnings surge rally buy strong record profit growth bullish upgrade",
        )
        analyst = MarketAnalyst()
        score, rationale = analyst._score_sentiment("NVDA")
        assert score > 50

    def test_negative_news_scores_below_50(self, monkeypatch):
        monkeypatch.setattr(
            "tools.stocks_tool.get_stock_news",
            lambda symbol: "AAPL miss fall drop decline weak loss warning bearish sell downgrade layoff",
        )
        analyst = MarketAnalyst()
        score, rationale = analyst._score_sentiment("AAPL")
        assert score < 50

    def test_no_signal_words_returns_neutral(self, monkeypatch):
        monkeypatch.setattr(
            "tools.stocks_tool.get_stock_news",
            lambda symbol: "No news available for this symbol today.",
        )
        analyst = MarketAnalyst()
        score, rationale = analyst._score_sentiment("XYZ")
        assert score == 50.0

    def test_exception_returns_neutral(self, monkeypatch):
        def boom(symbol):
            raise RuntimeError("fail")
        monkeypatch.setattr("tools.stocks_tool.get_stock_news", boom)
        analyst = MarketAnalyst()
        score, rationale = analyst._score_sentiment("XYZ")
        assert score == 50.0
