"""리스크 관리: 포지션 사이징(ATR 변동성 반영), 손절/트레일링 스탑, 일일 손실 한도(kill switch).

실시간 트레이더가 주문 실행 전 반드시 이 클래스를 거치도록 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd


def compute_atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    """최근 캔들 기준 ATR(평균 실질 변동폭)을 현재가 대비 비율로 반환한다.

    ATR% 가 클수록(변동성이 클수록) 포지션 배분을 줄이는 데 사용한다.
    데이터가 부족하면 0.0 을 반환한다 (사이징 축소 미적용).
    """
    if len(df) < period + 1:
        return 0.0
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().iloc[-1]
    last_price = float(close.iloc[-1])
    if last_price <= 0:
        return 0.0
    return float(atr) / last_price


@dataclass
class RiskManager:
    max_alloc_pct: float = 0.30
    stop_loss_pct: float = 0.05
    trailing_stop_pct: float = 0.08
    daily_loss_limit_pct: float = 0.03
    min_order_krw: float = 5000
    # 포지션의 일일 기대 변동(ATR%)이 자본 대비 이 비율이 되도록 배분 축소.
    # 예: 0.01 이고 ATR%가 5%면 배분 = min(max_alloc, 0.01/0.05=20%).
    vol_risk_budget_pct: float = 0.01
    atr_period: int = 14

    _day: date = field(default_factory=date.today, init=False)
    _day_start_equity: float | None = field(default=None, init=False)
    _realized_pnl_today: float = field(default=0.0, init=False)
    _halted: bool = field(default=False, init=False)

    def _roll_day_if_needed(self, equity: float) -> None:
        today = date.today()
        if today != self._day or self._day_start_equity is None:
            self._day = today
            self._day_start_equity = equity
            self._realized_pnl_today = 0.0
            self._halted = False

    def record_realized_pnl(self, pnl_krw: float, equity: float) -> None:
        """매도 체결로 실현손익이 발생했을 때 호출."""
        self._roll_day_if_needed(equity)
        self._realized_pnl_today += pnl_krw
        if self._day_start_equity and self._day_start_equity > 0:
            loss_pct = -self._realized_pnl_today / self._day_start_equity
            if loss_pct >= self.daily_loss_limit_pct:
                self._halted = True

    def is_halted(self, equity: float) -> bool:
        """일일 손실 한도 도달로 당일 신규 매수가 금지된 상태인지."""
        self._roll_day_if_needed(equity)
        return self._halted

    def max_order_krw(self, total_equity: float, cash: float) -> float:
        """이번 매수 주문에 쓸 수 있는 최대 KRW 금액 (고정 배분 상한)."""
        cap = total_equity * self.max_alloc_pct
        return max(0.0, min(cap, cash))

    def size_order_krw(self, total_equity: float, cash: float, atr_pct: float = 0.0) -> float:
        """ATR 변동성을 반영한 매수 금액. 변동성이 클수록 배분을 줄인다.

        atr_pct <= 0 이면 (데이터 부족 등) 고정 배분 상한만 적용한다.
        """
        alloc_pct = self.max_alloc_pct
        if atr_pct > 0 and self.vol_risk_budget_pct > 0:
            alloc_pct = min(self.max_alloc_pct, self.vol_risk_budget_pct / atr_pct)
        return max(0.0, min(total_equity * alloc_pct, cash))

    def can_place_buy(self, total_equity: float, cash: float) -> tuple[bool, str]:
        if self.is_halted(total_equity):
            return False, "일일 손실 한도 도달로 당일 매수가 중단되었습니다 (kill switch)"
        amount = self.max_order_krw(total_equity, cash)
        if amount < self.min_order_krw:
            return False, f"주문 가능 금액({amount:,.0f}원)이 최소 주문금액({self.min_order_krw:,.0f}원) 미만입니다"
        return True, ""

    def should_stop_loss(self, entry_price: float, current_price: float) -> bool:
        if entry_price <= 0:
            return False
        loss_pct = (entry_price - current_price) / entry_price
        return loss_pct >= self.stop_loss_pct

    def should_trailing_stop(self, high_water_mark: float, current_price: float) -> bool:
        """진입 후 최고가 대비 trailing_stop_pct 이상 하락하면 청산 (이익 보호)."""
        if high_water_mark <= 0:
            return False
        drawdown_pct = (high_water_mark - current_price) / high_water_mark
        return drawdown_pct >= self.trailing_stop_pct
