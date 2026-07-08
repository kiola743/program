import numpy as np
import pandas as pd
import pytest

from quant.backtest.engine import run_backtest
from quant.risk.manager import RiskManager, compute_atr_pct
from quant.strategy.base import Strategy
from quant.strategy.regime import align_regime, latest_regime_ok, regime_ok


def make_df(closes: list[float], spread: float = 0.01) -> pd.DataFrame:
    close = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": close * (1 + spread),
        "low": close * (1 - spread),
        "close": close,
        "volume": [100.0] * len(closes),
    })


class AlwaysLongStrategy(Strategy):
    name = "always_long"

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=df.index)


# ----- ATR 사이징 -----

def test_compute_atr_pct_flat_market_near_spread():
    df = make_df([100.0] * 30, spread=0.01)
    atr_pct = compute_atr_pct(df, period=14)
    # 고저 폭이 2%인 횡보장 -> ATR% 약 2%
    assert 0.015 < atr_pct < 0.025


def test_compute_atr_pct_insufficient_data():
    df = make_df([100.0] * 5)
    assert compute_atr_pct(df, period=14) == 0.0


def test_size_order_krw_scales_down_with_volatility():
    risk = RiskManager(max_alloc_pct=0.30, vol_risk_budget_pct=0.01)
    # 저변동성(ATR 1%) -> 상한 그대로 30%
    assert risk.size_order_krw(1_000_000, 1_000_000, atr_pct=0.01) == pytest.approx(300_000)
    # 고변동성(ATR 10%) -> 0.01/0.10 = 10%로 축소
    assert risk.size_order_krw(1_000_000, 1_000_000, atr_pct=0.10) == pytest.approx(100_000)
    # ATR 정보 없음 -> 상한 적용
    assert risk.size_order_krw(1_000_000, 1_000_000, atr_pct=0.0) == pytest.approx(300_000)


# ----- 트레일링 스탑 -----

def test_should_trailing_stop():
    risk = RiskManager(trailing_stop_pct=0.08)
    assert risk.should_trailing_stop(high_water_mark=100, current_price=91) is True
    assert risk.should_trailing_stop(high_water_mark=100, current_price=95) is False
    assert risk.should_trailing_stop(high_water_mark=0, current_price=95) is False


def test_backtest_trailing_stop_exits_after_peak_drop():
    # 100 -> 150 급등 후 120으로 하락: 8% 트레일링이면 고점 근처에서 청산돼야 함
    closes = [100, 110, 130, 150, 148, 138, 120, 110]
    df = make_df(closes, spread=0.005)
    result = run_backtest(df, AlwaysLongStrategy(), initial_capital=1_000_000,
                          fee_pct=0.0005, slippage_pct=0.0005, trailing_stop_pct=0.08)
    no_stop = run_backtest(df, AlwaysLongStrategy(), initial_capital=1_000_000,
                           fee_pct=0.0005, slippage_pct=0.0005)
    # 트레일링 스탑이 고점 이후 하락 구간 손실을 줄였는지
    assert result.equity.iloc[-1] > no_stop.equity.iloc[-1]
    assert result.trades == 1  # 스탑으로 한 번 청산됨


def test_backtest_stop_loss_limits_loss():
    closes = [100, 100, 60, 40]  # 진입 직후 급락
    df = make_df(closes, spread=0.005)
    result = run_backtest(df, AlwaysLongStrategy(), initial_capital=1_000_000,
                          fee_pct=0.0005, slippage_pct=0.0005, stop_loss_pct=0.05)
    # 5% 손절이면 손실이 대략 그 수준에서 멈춰야 함 (수수료/슬리피지 감안 -7% 이내)
    assert result.equity.iloc[-1] > 1_000_000 * 0.93
    assert result.trades == 1


# ----- 레짐 필터 -----

def test_regime_ok_above_and_below_ma():
    up = make_df(list(np.linspace(100, 200, 250)))
    assert latest_regime_ok(up, ma_period=200) is True
    down = make_df(list(np.linspace(200, 100, 250)))
    assert latest_regime_ok(down, ma_period=200) is False


def test_regime_ok_defaults_true_before_ma_ready():
    df = make_df([100.0] * 50)
    ok = regime_ok(df, ma_period=200)
    assert ok.all()  # MA 계산 전 구간은 필터 미적용


def test_backtest_regime_blocks_entry():
    closes = [100.0] * 10
    df = make_df(closes)
    regime = pd.Series(False, index=df.index)  # 전 구간 하락 레짐
    result = run_backtest(df, AlwaysLongStrategy(), initial_capital=1_000_000,
                          regime=regime)
    assert result.trades == 0
    assert result.equity.iloc[-1] == pytest.approx(1_000_000)


def test_align_regime_ffill():
    base_idx = pd.date_range("2024-01-01", periods=5, freq="D")
    regime = pd.Series([True, True, False, False, True], index=base_idx)
    target_idx = pd.date_range("2024-01-02", periods=5, freq="D")  # 하루 어긋남 + 초과
    aligned = align_regime(regime, target_idx)
    assert aligned.iloc[0] == True  # 01-02
    assert aligned.iloc[1] == False  # 01-03
    assert aligned.iloc[-1] == True  # 01-06 은 마지막 값 유지
