"""절대 모멘텀 전략 (듀얼 모멘텀의 시계열 축).

lookback일 수익률이 양수이고 종가가 ma_filter일 이동평균 위일 때만 보유.
"과거 N개월간 오른 자산은 계속 오르는 경향" (Antonacci 절대 모멘텀)에
추세 필터를 더해 횡보장 잦은 진입을 줄인다.
"""

from __future__ import annotations

import pandas as pd

from quant.strategy.base import Strategy


class AbsoluteMomentumStrategy(Strategy):
    name = "abs_momentum"

    def __init__(self, lookback: int = 90, ma_filter: int = 50):
        super().__init__(lookback=lookback, ma_filter=ma_filter)
        self.lookback = lookback
        self.ma_filter = ma_filter

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        momentum = close / close.shift(self.lookback) - 1
        ma = close.rolling(self.ma_filter).mean()
        long_cond = (momentum > 0) & (close > ma)
        return long_cond.astype(float).fillna(0.0)
