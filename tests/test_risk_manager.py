from quant.risk.manager import RiskManager


def test_max_order_krw_respects_alloc_and_cash():
    risk = RiskManager(max_alloc_pct=0.3)
    assert risk.max_order_krw(total_equity=1_000_000, cash=1_000_000) == 300_000
    assert risk.max_order_krw(total_equity=1_000_000, cash=100_000) == 100_000


def test_can_place_buy_rejects_below_min_order():
    risk = RiskManager(max_alloc_pct=0.3, min_order_krw=5000)
    ok, reason = risk.can_place_buy(total_equity=10_000, cash=10_000)
    assert ok is False
    assert "최소 주문금액" in reason


def test_daily_loss_limit_halts_trading():
    risk = RiskManager(daily_loss_limit_pct=0.03)
    equity = 1_000_000
    assert risk.is_halted(equity) is False
    risk.record_realized_pnl(pnl_krw=-40_000, equity=equity)  # -4% > 3% 한도
    assert risk.is_halted(equity) is True
    ok, reason = risk.can_place_buy(equity, cash=equity)
    assert ok is False
    assert "kill switch" in reason


def test_daily_loss_limit_not_triggered_below_threshold():
    risk = RiskManager(daily_loss_limit_pct=0.03)
    equity = 1_000_000
    risk.record_realized_pnl(pnl_krw=-10_000, equity=equity)  # -1%
    assert risk.is_halted(equity) is False


def test_should_stop_loss():
    risk = RiskManager(stop_loss_pct=0.05)
    assert risk.should_stop_loss(entry_price=100, current_price=94) is True
    assert risk.should_stop_loss(entry_price=100, current_price=96) is False
