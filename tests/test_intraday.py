import numpy as np
import pandas as pd
import pytest

from quant.backtest.intraday import run_vb_intraday_backtest


def make_day_df(rows: list[dict], start: str = "2024-01-01 09:00") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=idx)


def make_minutes(day_start: pd.Timestamp, closes: list[float], freq_min: int = 60) -> pd.DataFrame:
    idx = pd.date_range(day_start, periods=len(closes), freq=f"{freq_min}min")
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": close * 1.001,
        "low": close * 0.999,
        "close": close,
        "volume": 10.0,
    })


def test_intraday_fill_at_target_price():
    # 전일 range=10 (high 105, low 95), k=0.5 -> 둘째날 목표가 = open(100) + 5 = 105
    day_df = make_day_df([
        {"open": 100, "high": 105, "low": 95, "close": 100, "volume": 1},
        {"open": 100, "high": 110, "low": 99, "close": 108, "volume": 1},
    ])
    # 둘째날 분봉: 100 -> 103 -> 106(돌파) -> 108
    minutes = make_minutes(day_df.index[1], [100, 103, 106, 108])
    result = run_vb_intraday_backtest(day_df, minutes, k=0.5,
                                      initial_capital=1_000_000,
                                      fee_pct=0.0, slippage_pct=0.0)
    assert result.trades == 1
    # 목표가 105에 체결, 108에 청산 -> 수익률 약 +2.857%
    assert result.equity.iloc[-1] == pytest.approx(1_000_000 * 108 / 105, rel=1e-6)


def test_intraday_no_breakout_no_trade():
    day_df = make_day_df([
        {"open": 100, "high": 105, "low": 95, "close": 100, "volume": 1},
        {"open": 100, "high": 104, "low": 99, "close": 103, "volume": 1},
    ])
    # 분봉이 목표가(105)에 못 미침
    minutes = make_minutes(day_df.index[1], [100, 102, 103, 103])
    result = run_vb_intraday_backtest(day_df, minutes, k=0.5,
                                      fee_pct=0.0, slippage_pct=0.0)
    assert result.trades == 0
    assert result.equity.iloc[-1] == pytest.approx(result.equity.iloc[0])


def test_intraday_gap_open_fills_at_open_not_target():
    # 목표가 = 100 + 0.5*10 = 105. 첫 분봉 시가가 이미 107이면 (돌파 순간을 못 잡고
    # 갭으로 시작) 목표가 105가 아니라 시가 107에 체결돼야 함 (더 불리한 가격)
    day_df = make_day_df([
        {"open": 100, "high": 105, "low": 95, "close": 100, "volume": 1},
        {"open": 100, "high": 112, "low": 99, "close": 110, "volume": 1},
    ])
    minutes = make_minutes(day_df.index[1], [107, 109, 110, 110])
    # make_minutes 는 첫 분봉 open을 첫 close로 두므로 open=107 > 목표가 105
    result = run_vb_intraday_backtest(day_df, minutes, k=0.5,
                                      fee_pct=0.0, slippage_pct=0.0)
    assert result.trades == 1
    assert result.equity.iloc[-1] == pytest.approx(1_000_000 * 110 / 107, rel=1e-6)


def test_intraday_requires_minute_data():
    day_df = make_day_df([
        {"open": 100, "high": 105, "low": 95, "close": 100, "volume": 1},
        {"open": 100, "high": 110, "low": 99, "close": 108, "volume": 1},
    ])
    with pytest.raises(ValueError):
        run_vb_intraday_backtest(day_df, pd.DataFrame(), k=0.5)


def test_intraday_fees_reduce_returns():
    day_df = make_day_df([
        {"open": 100, "high": 105, "low": 95, "close": 100, "volume": 1},
        {"open": 100, "high": 110, "low": 99, "close": 108, "volume": 1},
    ])
    minutes = make_minutes(day_df.index[1], [100, 103, 106, 108])
    no_fee = run_vb_intraday_backtest(day_df, minutes, k=0.5, fee_pct=0.0, slippage_pct=0.0)
    with_fee = run_vb_intraday_backtest(day_df, minutes, k=0.5, fee_pct=0.0005,
                                        slippage_pct=0.0005)
    assert with_fee.equity.iloc[-1] < no_fee.equity.iloc[-1]
