import numpy as np
import pandas as pd

from quant.backtest.walkforward import run_walkforward, summarize_folds
from quant.strategy.ma_momentum import MaMomentumStrategy


def make_trend_df(n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rets = rng.normal(0.001, 0.02, n)
    close = 100 * np.exp(np.cumsum(rets))
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": 100.0,
    }, index=dates)


def test_walkforward_produces_folds_with_out_of_sample_periods():
    df = make_trend_df(400)
    param_spec = {"fast": [5, 10], "slow": [20, 40]}
    folds = run_walkforward(df, MaMomentumStrategy, param_spec, train_days=200, test_days=50)

    assert len(folds) >= 2
    for fold in folds:
        # train/test 구간이 겹치지 않아야 함 (미래 데이터로 파라미터를 고르지 않음)
        assert fold.train_end < fold.test_start
        assert fold.best_params["fast"] in (5, 10)


def test_summarize_folds_aggregates_oos_metrics():
    df = make_trend_df(400)
    param_spec = {"fast": [5, 10], "slow": [20, 40]}
    folds = run_walkforward(df, MaMomentumStrategy, param_spec, train_days=200, test_days=50)
    summary = summarize_folds(folds)

    assert summary["폴드 수"] == len(folds)
    assert isinstance(summary["OOS 평균수익률(%)"], float)
    assert 0 <= summary["수익 폴드 비율(%)"] <= 100


def test_summarize_folds_empty_list():
    assert summarize_folds([]) == {}
