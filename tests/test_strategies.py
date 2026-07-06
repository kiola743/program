import numpy as np
import pandas as pd
import pytest

from quant.strategy.ma_momentum import MaMomentumStrategy
from quant.strategy.mean_reversion import MeanReversionStrategy
from quant.strategy.volatility_breakout import VolatilityBreakoutStrategy


def make_df(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    close = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": [100.0] * n,
    })


def test_volatility_breakout_buys_on_strong_up_move():
    # 이전 range가 작고 시가 대비 크게 상승하면 돌파 조건 충족
    df = make_df([100, 100, 100, 130])
    strat = VolatilityBreakoutStrategy(k=0.5)
    target = strat.target_position(df)
    assert target.iloc[-1] == 1.0


def test_volatility_breakout_no_buy_flat_market():
    df = make_df([100, 100, 100, 100.1])
    strat = VolatilityBreakoutStrategy(k=0.9)
    target = strat.target_position(df)
    assert target.iloc[-1] == 0.0


def test_ma_momentum_uptrend_holds():
    closes = list(np.linspace(100, 200, 40))
    df = make_df(closes)
    strat = MaMomentumStrategy(fast=5, slow=20)
    target = strat.target_position(df)
    assert target.iloc[-1] == 1.0


def test_ma_momentum_downtrend_flat():
    closes = list(np.linspace(200, 100, 40))
    df = make_df(closes)
    strat = MaMomentumStrategy(fast=5, slow=20)
    target = strat.target_position(df)
    assert target.iloc[-1] == 0.0


def test_mean_reversion_buys_after_drop():
    # 30일 평탄 후 급락 -> RSI 급락 + 볼린저 하단 이탈로 매수 시그널 기대
    closes = [100.0] * 25 + [95, 90, 85, 80, 75]
    df = make_df(closes)
    strat = MeanReversionStrategy(rsi_period=14, rsi_buy=30, rsi_sell=70,
                                   bb_period=20, bb_std=2.0)
    target = strat.target_position(df)
    assert target.iloc[-1] == 1.0


def test_latest_signal_transitions():
    df = make_df([100, 100, 100, 130])
    strat = VolatilityBreakoutStrategy(k=0.5)
    signal = strat.latest_signal(df)
    from quant.strategy.base import Signal
    assert signal == Signal.BUY
