"""벡터화 백테스트 엔진.

전략의 target_position(0/1 시리즈)을 받아 포지션 전환 시점마다 수수료+슬리피지를
반영해 자산 곡선을 계산한다. 다음날 시가 체결이 아닌 당일 종가 체결로 근사한다
(전략의 target_position 자체가 "이 캔들 마감 시점 포지션"을 의미하므로 실시간
트레이더의 "캔들 마감 확인 후 즉시 시장가 주문" 동작과 일치한다).

옵션 리스크 장치 (라이브 트레이더와 동일 로직을 백테스트에서 미리 검증):
- stop_loss_pct: 진입가 대비 손실률 도달 시 청산 (바 저가 기준 트리거)
- trailing_stop_pct: 진입 후 최고가 대비 하락률 도달 시 청산
- regime: 시점별 상승장 여부(bool 시리즈). False 구간은 신규 진입 금지 + 보유분 청산
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
    stop_loss_pct: float | None = None,
    trailing_stop_pct: float | None = None,
    regime: pd.Series | None = None,
) -> BacktestResult:
    if len(df) < 2:
        raise ValueError("백테스트에는 최소 2개 이상의 캔들이 필요합니다")

    target = strategy.target_position(df).fillna(0.0)
    if regime is not None:
        target = target * regime.astype(float)
    close, high, low = df["close"], df["high"], df["low"]

    cash = initial_capital
    coin_qty = 0.0
    equity_curve = []
    trade_returns: list[float] = []
    entry_cost = 0.0
    entry_price = 0.0
    hwm = 0.0  # high water mark (트레일링 스탑용)
    holding = False
    prev_target = 0.0

    def do_exit(exec_price: float) -> None:
        nonlocal cash, coin_qty, holding
        exec_price = exec_price * (1 - slippage_pct)
        gross = coin_qty * exec_price
        fee = gross * fee_pct
        cash = gross - fee
        if entry_cost > 0:
            trade_returns.append(cash / entry_cost - 1)
        coin_qty = 0.0
        holding = False

    for i in range(len(df)):
        price = close.iloc[i]
        pos = target.iloc[i]

        if holding:
            hwm = max(hwm, float(high.iloc[i]))
            stop_price = entry_price * (1 - stop_loss_pct) if stop_loss_pct else None
            trail_price = hwm * (1 - trailing_stop_pct) if trailing_stop_pct else None

            if stop_price is not None and float(low.iloc[i]) <= stop_price:
                do_exit(stop_price)  # 장중 저가가 손절선에 닿았다고 가정
            elif trail_price is not None and float(low.iloc[i]) <= trail_price:
                do_exit(trail_price)
            elif pos <= 0:
                do_exit(price)  # 시그널/레짐 종료 → 종가 청산
        else:
            # 신규 진입은 목표 포지션이 0->1로 전환될 때만 (손절 후 즉시 재진입 방지,
            # 라이브 트레이더의 latest_signal 전환 감지와 동일한 동작)
            if pos > 0 and prev_target <= 0 and cash > 0:
                exec_price = price * (1 + slippage_pct)
                fee = cash * fee_pct
                coin_qty = (cash - fee) / exec_price
                entry_cost = cash
                entry_price = exec_price
                hwm = float(high.iloc[i])
                cash = 0.0
                holding = True

        equity_curve.append(cash + coin_qty * price)
        prev_target = pos

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
