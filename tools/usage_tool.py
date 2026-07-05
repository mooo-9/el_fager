"""
usage_report — spoken-friendly API cost and performance report.
Reads data/telemetry/*.jsonl written by core/telemetry.py.
cp1252-safe output (TTS-bound).
"""


def usage_report(days: int = 1) -> str:
    from core.telemetry import summarize
    days = max(1, min(int(days or 1), 90))
    s = summarize(days=days)
    if s["requests"] == 0:
        period = "today" if days == 1 else f"the last {days} days"
        return f"No API usage recorded for {period}."
    period = "Today" if days == 1 else f"Last {days} days"
    parts = [
        f"{period}: {s['requests']} API calls costing about "
        f"${s['cost_usd']:.2f}.",
        f"Tokens: {s['input_tokens']:,} in, {s['output_tokens']:,} out.",
        f"Average response time {s['avg_latency_ms'] / 1000:.1f} seconds.",
    ]
    if s["by_source"]:
        top = sorted(s["by_source"].items(),
                     key=lambda kv: -kv[1]["cost_usd"])[:3]
        breakdown = ", ".join(
            f"{name} ${b['cost_usd']:.2f} ({b['requests']} calls)"
            for name, b in top
        )
        parts.append(f"Breakdown: {breakdown}.")
    return " ".join(parts)
