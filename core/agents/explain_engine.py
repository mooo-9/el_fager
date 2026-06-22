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
