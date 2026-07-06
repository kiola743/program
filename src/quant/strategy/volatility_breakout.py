"""래리 윌리엄스 변동성 돌파 전략.

목표가 = 당일 시가 + (전일 고가-저가 range) * k
당일 고가가 목표가를 돌파하면 매수, 익일 시가에 매도(1일 보유)하는 것이 원형이나,
여기서는 종가 기준 벡터화를 위해 "당일 종가가 목표가 이상이면 그날 보유, 아니면 현금"
으로 근사한다 (일봉 백테스트/실시간 캔들마감 트레이더 모두 동일 로직 재사용).
"""

from __future__ import annotations

import pandas as pd

from quant.strategy.base import Strategy


class VolatilityBreakoutStrategy(Strategy):
    name = "volatility_breakout"

    def __init__(self, k: float = 0.5):
        super().__init__(k=k)
        self.k = k

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        prev_range = (df["high"] - df["low"]).shift(1)
        target_price = df["open"] + prev_range * self.k
        breakout = df["close"] >= target_price
        return breakout.astype(float).fillna(0.0)
