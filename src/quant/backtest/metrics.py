"""백테스트 성과지표 계산."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BacktestMetrics:
    total_return_pct: float
    cagr_pct: float
    mdd_pct: float
    sharpe: float
    win_rate_pct: float
    num_trades: int
    final_equity: float

    def as_dict(self) -> dict:
        return {
            "총수익률(%)": round(self.total_return_pct, 2),
            "CAGR(%)": round(self.cagr_pct, 2),
            "MDD(%)": round(self.mdd_pct, 2),
            "샤프비율": round(self.sharpe, 2),
            "승률(%)": round(self.win_rate_pct, 2),
            "거래횟수": self.num_trades,
            "최종자산": round(self.final_equity, 0),
        }


def compute_metrics(
    equity: pd.Series, trade_returns: list[float], periods_per_year: float = 365.0
) -> BacktestMetrics:
    """equity: 시점별 총자산 시리즈. trade_returns: 청산된 매매 각각의 수익률(소수)."""
    initial = equity.iloc[0]
    final = equity.iloc[-1]
    total_return_pct = (final / initial - 1) * 100

    n_periods = len(equity)
    years = max(n_periods / periods_per_year, 1e-9)
    cagr_pct = ((final / initial) ** (1 / years) - 1) * 100 if final > 0 else -100.0

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    mdd_pct = drawdown.min() * 100

    daily_ret = equity.pct_change().dropna()
    if daily_ret.std() > 0:
        sharpe = (daily_ret.mean() / daily_ret.std()) * np.sqrt(periods_per_year)
    else:
        sharpe = 0.0

    num_trades = len(trade_returns)
    wins = sum(1 for r in trade_returns if r > 0)
    win_rate_pct = (wins / num_trades * 100) if num_trades > 0 else 0.0

    return BacktestMetrics(
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        mdd_pct=mdd_pct,
        sharpe=sharpe,
        win_rate_pct=win_rate_pct,
        num_trades=num_trades,
        final_equity=final,
    )
