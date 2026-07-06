import pandas as pd
import pytest

from quant.backtest.engine import buy_and_hold, run_backtest
from quant.strategy.base import Strategy


class AlwaysLongStrategy(Strategy):
    name = "always_long"

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=df.index)


class AlwaysFlatStrategy(Strategy):
    name = "always_flat"

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(0.0, index=df.index)


def make_df(closes: list[float]) -> pd.DataFrame:
    close = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": [100.0] * len(closes),
    })


def test_always_flat_preserves_capital_minus_nothing():
    df = make_df([100, 101, 99, 102, 98])
    result = run_backtest(df, AlwaysFlatStrategy(), initial_capital=1_000_000,
                          fee_pct=0.0005, slippage_pct=0.0005)
    assert result.equity.iloc[-1] == pytest.approx(1_000_000)
    assert result.trades == 0


def test_always_long_matches_buy_and_hold_direction():
    df = make_df([100, 110, 120, 130, 140])
    result = run_backtest(df, AlwaysLongStrategy(), initial_capital=1_000_000,
                          fee_pct=0.0005, slippage_pct=0.0005)
    # 상승장에서 계속 보유하면 수익이 나야 함 (수수료 고려해도 40% 상승 압도)
    assert result.equity.iloc[-1] > 1_000_000
    assert result.metrics.total_return_pct > 0


def test_fees_reduce_returns_on_round_trip():
    # 시가=종가로 왕복 거래(진입 다음날 바로 청산)했을 때 수수료만큼 손실
    df = make_df([100, 100, 100])
    strat_positions = pd.Series([1.0, 0.0, 0.0])

    class OneRoundTrip(Strategy):
        name = "one_round_trip"

        def target_position(self, df):
            return strat_positions.iloc[: len(df)]

    result = run_backtest(df, OneRoundTrip(), initial_capital=1_000_000,
                          fee_pct=0.0005, slippage_pct=0.0005)
    assert result.equity.iloc[-1] < 1_000_000
    assert result.trades == 1


def test_buy_and_hold_benchmark():
    df = make_df([100, 200])
    equity = buy_and_hold(df, initial_capital=1_000_000, fee_pct=0.0005)
    assert equity.iloc[-1] == pytest.approx(equity.iloc[0] * 2, rel=1e-3)


def test_backtest_requires_min_rows():
    df = make_df([100])
    with pytest.raises(ValueError):
        run_backtest(df, AlwaysLongStrategy())
