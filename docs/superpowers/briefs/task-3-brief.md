# Task 3 Brief: ExplainEngine

## Context
El Fager project at `C:\claude proj\el_fager`. Tasks 1 and 2 complete — 106 tests passing. You are implementing Task 3: the ExplainEngine, which calls Claude Haiku to answer plain-language trading questions.

## Global Constraints
- Python 3.14 — no walrus operator
- cp1252 safety — NO emojis, NO Arabic, NO U+2192 in any return string
- No new pip installs — anthropic is already installed
- Run `python -m pytest` from `C:\claude proj\el_fager`; existing 106 tests must stay green
- Use `claude-haiku-4-5-20251001` as the model — not sonnet, not any other model

## Files to create
- `core/agents/explain_engine.py`
- `tests/agents/test_explain_engine.py`

## Interface consumed (from Task 1 — already exists)
```python
# from core.agents.market_analyst import AnalysisResult
class AnalysisResult(NamedTuple):
    symbol: str
    conviction: float
    direction: str
    technical_score: float
    fundamental_score: float
    sentiment_score: float
    rationale: str
```

## Interface produced (Task 4 StocksAgent calls this)
```python
class ExplainEngine:
    def explain(self, query: str, symbol: str | None = None, analysis=None) -> str:
        """Returns a plain-language answer string. Never raises."""
    def _load_trades_context(self, symbol: str | None) -> str:
        """Reads data/trades.json, filters by symbol if provided. Returns '' if missing."""
```

## Module-level path variable (must be named exactly this — tests monkeypatch it)
```python
_TRADES_PATH = Path("data/trades.json")
```

## Tests to write FIRST

```python
# tests/agents/test_explain_engine.py
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
```

## Implementation

```python
# core/agents/explain_engine.py
"""
ExplainEngine -- answers "why/how/thesis" queries about trades and positions
using Claude Haiku with structured context. Falls back to raw analysis text
when the API is unavailable.
"""
import json
from pathlib import Path

_TRADES_PATH = Path("data/trades.json")


class ExplainEngine:
    def explain(
        self,
        query: str,
        symbol: str | None = None,
        analysis=None,
    ) -> str:
        """Return a plain-language answer to a trading query.

        analysis -- optional AnalysisResult from MarketAnalyst
        """
        trades_ctx = self._load_trades_context(symbol)
        context_parts: list[str] = []

        if analysis is not None:
            context_parts.append(
                f"Latest analysis for {analysis.symbol}:\n"
                f"Conviction: {analysis.conviction:.1f}% | Direction: {analysis.direction}\n"
                f"Technical: {analysis.technical_score:.0f}/100 | "
                f"Fundamental: {analysis.fundamental_score:.0f}/100 | "
                f"Sentiment: {analysis.sentiment_score:.0f}/100\n"
                f"Detail: {analysis.rationale}"
            )
        if trades_ctx:
            context_parts.append(f"Recent trades:\n{trades_ctx}")

        context = "\n\n".join(context_parts) if context_parts else "No current analysis available."

        prompt = (
            "You are El Fager's trading analyst. Answer the query in 2-3 sentences max, "
            "plain language, no jargon. No emojis.\n\n"
            f"Context:\n{context}\n\n"
            f"Query: {query}"
        )

        try:
            import anthropic
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception:
            if analysis is not None:
                return (
                    f"Analysis for {analysis.symbol}: conviction {analysis.conviction:.0f}%, "
                    f"direction {analysis.direction}. {analysis.rationale[:200]}"
                )
            return "Unable to generate explanation -- no analysis available."

    def _load_trades_context(self, symbol: str | None) -> str:
        if not _TRADES_PATH.exists():
            return ""
        try:
            trades = json.loads(_TRADES_PATH.read_text(encoding="utf-8"))
            if symbol:
                trades = [t for t in trades if t.get("symbol") == symbol]
            recent = trades[-5:]
            lines = [
                f"{t.get('timestamp', '')[:10]} "
                f"{t.get('side', '').upper()} "
                f"{t.get('qty', 0):.4f} "
                f"{t.get('symbol', '')} "
                f"@ ${t.get('price', 0):.2f} "
                f"(signal: {t.get('signal', 'unknown')})"
                for t in recent
            ]
            return "\n".join(lines)
        except Exception:
            return ""
```

## Steps
1. Write tests file first
2. Run `python -m pytest tests/agents/test_explain_engine.py -v` — confirm ModuleNotFoundError
3. Write implementation file
4. Run `python -m pytest tests/agents/test_explain_engine.py -v` — all 6 pass
5. Run `python -m pytest --tb=short -q` — full suite green (106 + 6 = 112 expected)
6. Commit: `git add core/agents/explain_engine.py tests/agents/test_explain_engine.py && git commit -m "feat: add ExplainEngine using Claude Haiku for plain-language trade explanations"`

## Report
Write to: `C:\claude proj\el_fager\docs\superpowers\briefs\task-3-report.md`
Include: Status, commit hash, test count, concerns.
