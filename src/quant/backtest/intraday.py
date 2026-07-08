"""분봉 기반 변동성 돌파 정밀 백테스트.

일봉 종가 근사(engine.py)는 "종가가 목표가 위였다"는 사실만 보고 종가에 체결한
것으로 계산하지만, 실제 변동성 돌파는 장중 목표가 돌파 **순간** 매수한다.
이 모듈은 분봉을 스캔해 돌파가 발생한 첫 분봉에서 체결가를 재현한다:

  체결가 = max(목표가, 해당 분봉 시가) × (1 + 슬리피지)

(분봉 시가가 이미 목표가를 넘어 갭으로 시작했다면 그 시가에 체결된다.)
청산은 당일 마지막 분봉 종가(≈ 일봉 종가). 같은 지표를 쓰므로 기존
BacktestMetrics 를 그대로 재사용한다.
"""

from __future__ import annotations

import pandas as pd

from quant.backtest.engine import BacktestResult
from quant.backtest.metrics import compute_metrics


def run_vb_intraday_backtest(
    day_df: pd.DataFrame,
    minute_df: pd.DataFrame,
    k: float = 0.5,
    initial_capital: float = 1_000_000,
    fee_pct: float = 0.0005,
    slippage_pct: float = 0.0005,
) -> BacktestResult:
    """day_df: 일봉(목표가 계산용), minute_df: 같은 기간 분봉(체결 재현용)."""
    if len(day_df) < 2:
        raise ValueError("백테스트에는 최소 2개 이상의 일봉이 필요합니다")
    if minute_df.empty:
        raise ValueError("분봉 데이터가 없습니다. `collect --intraday` 를 먼저 실행하세요")

    prev_range = (day_df["high"] - day_df["low"]).shift(1)
    targets = day_df["open"] + prev_range * k

    minute_df = minute_df.sort_index()
    day_index = day_df.index

    equity = initial_capital
    equity_curve: list[float] = []
    trade_returns: list[float] = []
    n_days_with_minutes = 0

    for i, (day_ts, target_price) in enumerate(targets.items()):
        # 업비트 일봉은 09:00 KST 시작이므로 "그 일봉의 분봉"은
        # [해당 일봉 시각, 다음 일봉 시각) 구간으로 자른다
        day_start = pd.Timestamp(day_ts)
        day_end = day_index[i + 1] if i + 1 < len(day_index) else day_start + pd.Timedelta(days=1)
        minutes = minute_df.loc[(minute_df.index >= day_start) & (minute_df.index < day_end)]
        if pd.isna(target_price) or minutes.empty:
            equity_curve.append(equity)
            continue
        n_days_with_minutes += 1
        breakout = minutes[minutes["high"] >= target_price]
        if breakout.empty:
            equity_curve.append(equity)
            continue

        first = breakout.iloc[0]
        # 분봉 시가가 이미 목표가 위면 갭 체결 (더 불리한 가격)
        fill_price = max(float(target_price), float(first["open"])) * (1 + slippage_pct)
        exit_price = float(minutes["close"].iloc[-1]) * (1 - slippage_pct)

        buy_fee = equity * fee_pct
        qty = (equity - buy_fee) / fill_price
        gross = qty * exit_price
        sell_fee = gross * fee_pct
        new_equity = gross - sell_fee

        trade_returns.append(new_equity / equity - 1)
        equity = new_equity
        equity_curve.append(equity)

    if n_days_with_minutes == 0:
        raise ValueError("일봉과 겹치는 분봉 데이터가 없습니다 (수집 기간 확인)")

    equity_series = pd.Series(equity_curve, index=day_df.index)
    metrics = compute_metrics(equity_series, trade_returns)
    return BacktestResult(equity=equity_series, metrics=metrics, trades=len(trade_returns))
