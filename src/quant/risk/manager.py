"""리스크 관리: 포지션 사이징, 손절, 일일 손실 한도(kill switch).

실시간 트레이더가 주문 실행 전 반드시 이 클래스를 거치도록 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class RiskManager:
    max_alloc_pct: float = 0.30
    stop_loss_pct: float = 0.05
    daily_loss_limit_pct: float = 0.03
    min_order_krw: float = 5000

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
        """이번 매수 주문에 쓸 수 있는 최대 KRW 금액."""
        cap = total_equity * self.max_alloc_pct
        return max(0.0, min(cap, cash))

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
