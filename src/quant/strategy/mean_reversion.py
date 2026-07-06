"""RSI + 볼린저밴드 평균회귀 전략.

RSI가 과매도 구간에서 반등하거나 종가가 볼린저 하단 아래일 때 매수 보유,
RSI 과매수 도달 또는 중심선(SMA) 회복 시 청산.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant.strategy.base import Strategy


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


class MeanReversionStrategy(Strategy):
    name = "mean_reversion"

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_buy: float = 30,
        rsi_sell: float = 70,
        bb_period: int = 20,
        bb_std: float = 2.0,
    ):
        super().__init__(
            rsi_period=rsi_period, rsi_buy=rsi_buy, rsi_sell=rsi_sell,
            bb_period=bb_period, bb_std=bb_std,
        )
        self.rsi_period = rsi_period
        self.rsi_buy = rsi_buy
        self.rsi_sell = rsi_sell
        self.bb_period = bb_period
        self.bb_std = bb_std

    def target_position(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        rsi = _rsi(close, self.rsi_period)
        mid = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std()
        lower = mid - self.bb_std * std

        buy_cond = (rsi <= self.rsi_buy) | (close <= lower)
        sell_cond = (rsi >= self.rsi_sell) | (close >= mid)

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
