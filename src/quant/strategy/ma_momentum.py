"""이동평균 교차 + 모멘텀 필터 전략.

단기 이평이 장기 이평 위에 있고(추세 상승) 종가가 장기 이평보다 높을 때 보유,
아니면 현금. 골든/데드크로스 기반 추세추종.
"""

from __future__ import annotations

import pandas as pd

from quant.strategy.base import Strategy


class MaMomentumStrategy(Strategy):
    name = "ma_momentum"

    def __init__(self, fast: int = 5, slow: int = 20):
        super().__init__(fast=fast, slow=slow)
        self.fast = fast
        self.slow = slow

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        fast_ma = df["close"].rolling(self.fast).mean()
        slow_ma = df["close"].rolling(self.slow).mean()
        long_cond = (fast_ma > slow_ma) & (df["close"] > slow_ma)
        return long_cond.astype(float).fillna(0.0)
