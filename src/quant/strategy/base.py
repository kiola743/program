"""전략 공통 인터페이스.

모든 전략은 OHLCV DataFrame을 받아 각 시점의 목표 포지션(0=현금, 1=풀매수)을
나타내는 target 시리즈를 반환한다. 벡터화 백테스트와 실시간 트레이더가 공유한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

import pandas as pd


class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Strategy(ABC):
    """전략 베이스 클래스. 서브클래스는 params 를 받아 시그널을 계산한다."""

    name: str = "base"

    def __init__(self, **params):
        self.params = params

    @abstractmethod
    def target_position(self, df: pd.DataFrame) -> pd.Series:
        """각 캔들 종가 시점 기준 목표 포지션(0~1) 시리즈. index는 df와 동일."""

    def latest_signal(self, df: pd.DataFrame) -> Signal:
        """실시간 트레이더용: 가장 최근 캔들 기준 매수/매도/보유 판단.

        직전 목표 포지션과 비교해 0->1 전환이면 BUY, 1->0 전환이면 SELL.
        """
        target = self.target_position(df)
        if len(target) < 2:
            return Signal.HOLD
        prev, curr = target.iloc[-2], target.iloc[-1]
        if prev <= 0 and curr > 0:
            return Signal.BUY
        if prev > 0 and curr <= 0:
            return Signal.SELL
        return Signal.HOLD
