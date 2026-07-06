"""거래소 어댑터 공통 인터페이스.

코인(업비트)과 주식(KIS)을 같은 인터페이스로 다루기 위한 추상 계층.
전략/리스크/트레이더는 이 인터페이스에만 의존한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd


@dataclass
class Balance:
    """보유 자산 1건 (예: KRW-BTC 포지션)."""

    market: str
    qty: float
    avg_price: float  # 평균 매수가 (KRW)

    @property
    def value_at(self) -> float:
        return self.qty * self.avg_price


@dataclass
class OrderResult:
    """체결 결과."""

    market: str
    side: str  # "buy" | "sell"
    price: float  # 체결가
    qty: float
    krw_amount: float  # 수수료 제외 체결 금액
    fee: float
    ts: datetime = field(default_factory=datetime.now)

    def __str__(self) -> str:
        side_kr = "매수" if self.side == "buy" else "매도"
        return (
            f"[{side_kr}] {self.market} 체결가 {self.price:,.0f} "
            f"수량 {self.qty:.8f} 금액 {self.krw_amount:,.0f}원 수수료 {self.fee:,.1f}원"
        )


class ExchangeAdapter(ABC):
    """시세 조회 + 주문 + 잔고 인터페이스."""

    name: str = "base"

    # ----- 시세 -----
    @abstractmethod
    def get_current_price(self, market: str) -> float: ...

    @abstractmethod
    def get_ohlcv(self, market: str, interval: str = "day", count: int = 200) -> pd.DataFrame:
        """open/high/low/close/volume 컬럼, DatetimeIndex(과거→최신) DataFrame."""

    # ----- 계좌 -----
    @abstractmethod
    def get_cash(self) -> float:
        """주문 가능 현금(KRW)."""

    @abstractmethod
    def get_position(self, market: str) -> Balance | None:
        """해당 마켓 보유 포지션. 없으면 None."""

    # ----- 주문 -----
    @abstractmethod
    def buy_market(self, market: str, krw_amount: float) -> OrderResult: ...

    @abstractmethod
    def sell_market(self, market: str, qty: float) -> OrderResult: ...

    # ----- 시장 특성 훅 (주식 어댑터가 오버라이드) -----
    def is_market_open(self, now: datetime | None = None) -> bool:
        """거래 가능 시간인지. 코인은 24시간이므로 항상 True."""
        return True

    def round_qty(self, market: str, qty: float) -> float:
        """주문 수량 단위 보정. 코인은 소수점 8자리, 주식은 1주 단위로 오버라이드."""
        return round(qty, 8)
