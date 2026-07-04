# Task 5 Report: Router refinement + brain.py wiring

## Status
COMPLETE

## Commit Hash
319ef34

## Test Summary
136 passed in 13.11s (127 existing + 9 new TestStocksAgentRouting tests)

## Changes Made
- `core/agents/router.py`: Added `_STOCKS_AGENT_KEYWORDS` list and inserted `("stocks_agent", _STOCKS_AGENT_KEYWORDS)` into `_LABEL_KEYWORDS` before the existing `"stocks"` entry, ensuring analytical/agentic queries route to StocksAgent while simple price lookups fall through to the instant-lane stocks handler.
- `core/brain.py`: Added `if intent == "stocks_agent"` branch in `_try_agent_dispatch()` to dispatch to `StocksAgent().run(task)`.
- `tests/agents/test_router.py`: Appended `TestStocksAgentRouting` class with 9 tests covering analyze, thesis, should-i-buy, why-did-you-buy, pause-trading, set-threshold, price-stays-stocks, scan-watchlist variants.

## Concerns
None. All existing tests remain green and the new intent label is cleanly ordered before the broader "stocks" keyword list.
