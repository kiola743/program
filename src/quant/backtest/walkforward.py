"""워크포워드 검증.

compare 명령의 백테스트는 전체 과거 데이터 전체 구간에서 가장 성과가 좋은
파라미터를 찾는데, 이는 과최적화(curve-fitting) 위험이 크다 — 그 파라미터가
정말 "안 본 미래 구간"에서도 통하는지는 알 수 없다.

워크포워드는 데이터를 (train, test) 구간으로 슬라이딩하며, 매 폴드마다
train 구간에서만 파라미터를 선택하고, 그 파라미터를 test 구간(선택에 전혀
쓰이지 않은 미래 데이터)에 적용한 성과만 집계한다. OOS(out-of-sample) 성과가
꾸준히 양(+)이 아니라면 해당 전략은 실전 투입을 재고해야 한다.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import pandas as pd

from quant.backtest.engine import run_backtest
from quant.backtest.metrics import BacktestMetrics
from quant.strategy.base import Strategy


@dataclass
class Fold:
    fold_idx: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    best_params: dict
    train_sharpe: float
    test_metrics: BacktestMetrics


def _param_grid(param_spec: dict) -> list[dict]:
    keys = list(param_spec.keys())
    combos = itertools.product(*param_spec.values())
    return [dict(zip(keys, values)) for values in combos]


def run_walkforward(
    df: pd.DataFrame,
    strategy_cls: type[Strategy],
    param_spec: dict,
    train_days: int,
    test_days: int,
    initial_capital: float = 1_000_000,
    fee_pct: float = 0.0005,
    slippage_pct: float = 0.0005,
    stop_loss_pct: float | None = None,
    trailing_stop_pct: float | None = None,
    regime: pd.Series | None = None,
) -> list[Fold]:
    """train 구간에서 샤프비율 최대 파라미터를 고른 뒤 test 구간에서만 평가한다.

    (train_days + test_days)를 한 스텝(=test_days)씩 밀며 슬라이딩한다.
    stop/trailing/regime 을 주면 라이브와 동일한 보호장치가 적용된 상태로 검증한다.
    """
    grid = _param_grid(param_spec)
    folds: list[Fold] = []
    n = len(df)
    start = 0
    fold_idx = 0

    def _bt(window_df: pd.DataFrame, params: dict):
        window_regime = regime.loc[window_df.index] if regime is not None else None
        return run_backtest(
            window_df, strategy_cls(**params), initial_capital, fee_pct, slippage_pct,
            stop_loss_pct=stop_loss_pct, trailing_stop_pct=trailing_stop_pct,
            regime=window_regime,
        )

    while start + train_days + test_days <= n:
        train_df = df.iloc[start : start + train_days]
        test_df = df.iloc[start + train_days : start + train_days + test_days]

        best_params: dict | None = None
        best_sharpe = float("-inf")
        for params in grid:
            try:
                result = _bt(train_df, params)
            except ValueError:
                continue
            if result.metrics.sharpe > best_sharpe:
                best_sharpe = result.metrics.sharpe
                best_params = params

        if best_params is not None:
            test_result = _bt(test_df, best_params)
            folds.append(Fold(
                fold_idx=fold_idx,
                train_start=train_df.index[0], train_end=train_df.index[-1],
                test_start=test_df.index[0], test_end=test_df.index[-1],
                best_params=best_params, train_sharpe=best_sharpe,
                test_metrics=test_result.metrics,
            ))

        start += test_days
        fold_idx += 1

    return folds


def summarize_folds(folds: list[Fold]) -> dict:
    if not folds:
        return {}
    n = len(folds)
    oos_returns = [float(f.test_metrics.total_return_pct) for f in folds]
    oos_sharpes = [float(f.test_metrics.sharpe) for f in folds]
    oos_mdds = [float(f.test_metrics.mdd_pct) for f in folds]
    positive_folds = sum(1 for r in oos_returns if r > 0)
    return {
        "폴드 수": n,
        "OOS 평균수익률(%)": round(sum(oos_returns) / n, 2),
        "OOS 평균샤프비율": round(sum(oos_sharpes) / n, 2),
        "OOS 평균MDD(%)": round(sum(oos_mdds) / n, 2),
        "수익 폴드 비율(%)": round(positive_folds / n * 100, 1),
    }
