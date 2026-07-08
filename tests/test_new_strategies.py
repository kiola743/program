import numpy as np
import pandas as pd

from quant.strategy.abs_momentum import AbsoluteMomentumStrategy
from quant.strategy.donchian import DonchianBreakoutStrategy


def make_df(closes: list[float]) -> pd.DataFrame:
    close = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": close * 1.005,
        "low": close * 0.995,
        "close": close,
        "volume": [100.0] * len(closes),
    })


def test_donchian_enters_on_new_high():
    # 20일 횡보 후 신고가 돌파
    closes = [100.0] * 25 + [120.0]
    df = make_df(closes)
    strat = DonchianBreakoutStrategy(entry_n=20, exit_n=10)
    target = strat.target_position(df)
    assert target.iloc[-1] == 1.0
    assert target.iloc[-2] == 0.0  # 돌파 전에는 미보유


def test_donchian_exits_on_low_break():
    # 돌파로 진입 후 급락해 10일 최저가 이탈
    closes = [100.0] * 25 + [120.0] + [121.0] * 10 + [90.0]
    df = make_df(closes)
    strat = DonchianBreakoutStrategy(entry_n=20, exit_n=10)
    target = strat.target_position(df)
    assert target.iloc[26] == 1.0   # 진입 유지 확인
    assert target.iloc[-1] == 0.0   # 최저가 이탈로 청산


def test_abs_momentum_holds_in_uptrend():
    closes = list(np.linspace(100, 300, 200))
    df = make_df(closes)
    strat = AbsoluteMomentumStrategy(lookback=90, ma_filter=50)
    target = strat.target_position(df)
    assert target.iloc[-1] == 1.0


def test_abs_momentum_flat_in_downtrend():
    closes = list(np.linspace(300, 100, 200))
    df = make_df(closes)
    strat = AbsoluteMomentumStrategy(lookback=90, ma_filter=50)
    target = strat.target_position(df)
    assert target.iloc[-1] == 0.0


def test_abs_momentum_flat_before_lookback():
    closes = list(np.linspace(100, 200, 50))  # lookback(90)보다 짧음
    df = make_df(closes)
    strat = AbsoluteMomentumStrategy(lookback=90, ma_filter=50)
    target = strat.target_position(df)
    assert (target == 0.0).all()
