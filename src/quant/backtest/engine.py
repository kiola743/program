"""벡터화 백테스트 엔진.

전략의 target_position(0/1 시리즈)을 받아 포지션 전환 시점마다 수수료+슬리피지를
반영해 자산 곡선을 계산한다. 다음날 시가 체결이 아닌 당일 종가 체결로 근사한다
(전략의 target_position 자체가 "이 캔들 마감 시점 포지션"을 의미하므로 실시간
트레이더의 "캔들 마감 확인 후 즉시 시장가 주문" 동작과 일치한다).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant.backtest.metrics import BacktestMetrics, compute_metrics
from quant.strategy.base import Strategy


@dataclass
class BacktestResult:
    equity: pd.Series
    metrics: BacktestMetrics
    trades: int


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    initial_capital: float = 1_000_000,
    fee_pct: float = 0.0005,
    slippage_pct: float = 0.0005,
) -> BacktestResult:
    if len(df) < 2:
        raise ValueError("백테스트에는 최소 2개 이상의 캔들이 필요합니다")

    target = strategy.target_position(df).fillna(0.0)
    close = df["close"]

    cash = initial_capital
    coin_qty = 0.0
    equity_curve = []
    trade_returns: list[float] = []
    entry_cost = 0.0
    round_trip_cost = fee_pct + slippage_pct  # 매수/매도 각각 1회씩 적용

    prev_pos = 0.0
    for i in range(len(df)):
        price = close.iloc[i]
        pos = target.iloc[i]

        if prev_pos <= 0 and pos > 0:
            # 진입: 슬리피지 반영해 불리한 가격에, 수수료 차감 후 매수
            exec_price = price * (1 + slippage_pct)
            fee = cash * fee_pct
            coin_qty = (cash - fee) / exec_price
            entry_cost = cash
            cash = 0.0
        elif prev_pos > 0 and pos <= 0:
            # 청산
            exec_price = price * (1 - slippage_pct)
            gross = coin_qty * exec_price
            fee = gross * fee_pct
            cash = gross - fee
            if entry_cost > 0:
                trade_returns.append(cash / entry_cost - 1)
            coin_qty = 0.0

        equity = cash + coin_qty * price
        equity_curve.append(equity)
        prev_pos = pos

    # 마지막 시점까지 보유 중이면 청산 가치로 평가(미실현 포함, trade_returns엔 미포함)
    equity_series = pd.Series(equity_curve, index=df.index)
    metrics = compute_metrics(equity_series, trade_returns)
    return BacktestResult(equity=equity_series, metrics=metrics, trades=len(trade_returns))


def buy_and_hold(df: pd.DataFrame, initial_capital: float = 1_000_000,
                  fee_pct: float = 0.0005) -> pd.Series:
    """벤치마크: 첫 캔들에 전량 매수 후 계속 보유."""
    entry = df["close"].iloc[0] * (1 + fee_pct)
    qty = initial_capital * (1 - fee_pct) / entry
    return df["close"] * qty
