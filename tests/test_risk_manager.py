"""Unit tests for core/risk_manager.py — pure logic, no file I/O."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.risk_manager as rm

_TEST_CFG = {
    "max_position_pct": 10,
    "stop_loss_pct": 8,
    "take_profit_pct": 15,
    "daily_loss_limit_pct": 5,
    "max_open_positions": 5,
}


def _patch(cfg=None):
    data = cfg or _TEST_CFG
    rm._load_config = lambda: data


def test_calc_position_size_basic():
    _patch()
    # 10% of $1000 at $100/share = 1.0 share
    assert abs(rm.calc_position_size(1000.0, 100.0) - 1.0) < 0.001


def test_calc_position_size_returns_zero_when_one_share_exceeds_cap():
    _patch()
    # 10% of $500 = $50 budget; one share costs $450 — must NOT force-buy it
    assert rm.calc_position_size(500.0, 450.0) == 0


def test_calc_position_size_floors_to_whole_shares():
    _patch()
    # 10% of $10,000 = $1,000 budget at $300/share -> floor(3.33) = 3
    assert rm.calc_position_size(10_000.0, 300.0) == 3


def test_get_stop_loss_price():
    _patch()
    # entry $100, stop 8% -> $92
    assert abs(rm.get_stop_loss_price(100.0) - 92.0) < 0.01


def test_get_take_profit_price():
    _patch()
    # entry $100, tp 15% -> $115
    assert abs(rm.get_take_profit_price(100.0) - 115.0) < 0.01


def test_can_open_position_allows_when_under_limit():
    _patch()
    allowed, msg = rm.can_open_position(3)
    assert allowed is True
    assert msg == "ok"


def test_can_open_position_allows_at_four():
    _patch()
    allowed, _ = rm.can_open_position(4)
    assert allowed is True


def test_can_open_position_blocks_at_limit():
    _patch()
    allowed, msg = rm.can_open_position(5)
    assert allowed is False
    assert "5" in msg


def test_can_open_position_blocks_above_limit():
    _patch()
    allowed, _ = rm.can_open_position(10)
    assert allowed is False


def test_is_daily_limit_not_hit_small_drop():
    _patch()
    # 3% drop — under 5% limit
    assert rm.is_daily_limit_hit(970.0, 1000.0) is False


def test_is_daily_limit_not_hit_exact_boundary():
    _patch()
    # exactly 5% drop — boundary is >=, so this IS hit
    assert rm.is_daily_limit_hit(950.0, 1000.0) is True


def test_is_daily_limit_hit_large_drop():
    _patch()
    # 6% drop — over limit
    assert rm.is_daily_limit_hit(940.0, 1000.0) is True


def test_stop_loss_custom_pct():
    _patch({"max_position_pct": 10, "stop_loss_pct": 5,
            "take_profit_pct": 15, "daily_loss_limit_pct": 5, "max_open_positions": 5})
    assert abs(rm.get_stop_loss_price(200.0) - 190.0) < 0.01
