"""돈치안 채널 돌파 전략 (터틀 트레이딩 계열 추세추종).

종가가 직전 entry_n일 최고가를 넘으면 매수, 직전 exit_n일 최저가를 깨면 청산.
진입 채널보다 청산 채널을 짧게 잡아 추세가 꺾이면 빨리 나온다.
"""

from __future__ import annotations

import pandas as pd

from quant.strategy.base import Strategy


class DonchianBreakoutStrategy(Strategy):
    name = "donchian"

    def __init__(self, entry_n: int = 20, exit_n: int = 10):
        super().__init__(entry_n=entry_n, exit_n=exit_n)
        self.entry_n = entry_n
        self.exit_n = exit_n

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        # shift(1): 오늘 종가는 채널 계산에서 제외 (당일 정보로 당일 돌파 판정 방지)
        upper = df["high"].rolling(self.entry_n).max().shift(1)
        lower = df["low"].rolling(self.exit_n).min().shift(1)

        buy_cond = close > upper
        sell_cond = close < lower

        position = pd.Series(0.0, index=df.index)
        holding = False
        for i in range(len(df)):
            if holding:
                if bool(sell_cond.iloc[i]):
                    holding = False
            else:
                if bool(buy_cond.iloc[i]):
                    holding = True
            position.iloc[i] = 1.0 if holding else 0.0
        return position
