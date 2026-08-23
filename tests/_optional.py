"""Skip markers for tests that need an optional runtime dependency.

Several El Fager features import their heavy dependency lazily (playwright,
pyautogui, yfinance, alpaca, ...). Those deps are not installed in every
environment — CI runs headless and has no browser binaries or display — so the
tests covering them must skip, not fail.
"""
import importlib.util

import pytest


def requires(module: str):
    """Skip the decorated test/class when `module` is not importable."""
    return pytest.mark.skipif(
        importlib.util.find_spec(module) is None,
        reason=f"optional dependency {module!r} not installed",
    )
