"""실시간 매매 루프. paper/live 어댑터 공용 — 어댑터 구현체만 교체하면 된다.

동작: poll_seconds 주기로 각 마켓의 최근 캔들을 가져와 전략 시그널을 확인하고,
리스크 매니저 승인 하에 매수/매도하며, 매 체결과 에러를 디스코드로 알린다.
손절(stop_loss_pct)은 시그널과 무관하게 매 루프마다 별도로 확인한다.
"""

from __future__ import annotations

import logging
import time

from quant.exchange.base import ExchangeAdapter
from quant.live.statelog import StateLog
from quant.notify.discord import DiscordNotifier
from quant.risk.manager import RiskManager
from quant.strategy.base import Signal, Strategy

logger = logging.getLogger("quant.live")


class LiveTrader:
    def __init__(
        self,
        exchange: ExchangeAdapter,
        strategy: Strategy,
        markets: list[str],
        risk: RiskManager,
        notifier: DiscordNotifier,
        interval: str = "day",
        lookback: int = 60,
        poll_seconds: int = 30,
        state_log: StateLog | None = None,
    ):
        self.exchange = exchange
        self.strategy = strategy
        self.markets = markets
        self.risk = risk
        self.notifier = notifier
        self.interval = interval
        self.lookback = lookback
        self.poll_seconds = poll_seconds
        self.state_log = state_log

    def _total_equity(self) -> float:
        equity = self.exchange.get_cash()
        for m in self.markets:
            pos = self.exchange.get_position(m)
            if pos:
                equity += pos.qty * self.exchange.get_current_price(m)
        return equity

    def _check_stop_loss(self, market: str) -> None:
        pos = self.exchange.get_position(market)
        if pos is None:
            return
        price = self.exchange.get_current_price(market)
        if self.risk.should_stop_loss(pos.avg_price, price):
            self.notifier.info(f"{market} 손절 조건 도달 (진입가 {pos.avg_price:,.0f} -> 현재가 {price:,.0f})")
            self._sell(market, pos.qty)

    def _sell(self, market: str, qty: float) -> None:
        pos = self.exchange.get_position(market)
        result = self.exchange.sell_market(market, qty)
        self.notifier.trade(str(result))
        if self.state_log:
            self.state_log.record_trade(self.exchange.name, result)
        if pos:
            pnl = (result.price - pos.avg_price) * result.qty - result.fee
            self.risk.record_realized_pnl(pnl, self._total_equity())

    def _buy(self, market: str) -> None:
        equity = self._total_equity()
        cash = self.exchange.get_cash()
        ok, reason = self.risk.can_place_buy(equity, cash)
        if not ok:
            self.notifier.info(f"{market} 매수 보류: {reason}")
            return
        amount = self.risk.max_order_krw(equity, cash)
        result = self.exchange.buy_market(market, amount)
        self.notifier.trade(str(result))
        if self.state_log:
            self.state_log.record_trade(self.exchange.name, result)

    def step(self) -> None:
        """한 주기 실행 (테스트 용이성을 위해 run()에서 분리)."""
        if self.state_log:
            try:
                self.state_log.record_equity(self.exchange.name, self._total_equity(),
                                             self.exchange.get_cash())
            except Exception:
                logger.exception("자산 스냅샷 기록 실패")
        for market in self.markets:
            try:
                if not self.exchange.is_market_open():
                    continue
                self._check_stop_loss(market)
                df = self.exchange.get_ohlcv(market, interval=self.interval, count=self.lookback)
                signal = self.strategy.latest_signal(df)
                pos = self.exchange.get_position(market)

                if signal == Signal.BUY and pos is None:
                    self._buy(market)
                elif signal == Signal.SELL and pos is not None:
                    self._sell(market, pos.qty)
            except Exception as e:  # 한 마켓의 오류가 전체 루프를 멈추면 안 됨
                logger.exception("%s 처리 중 오류", market)
                self.notifier.error(f"{market} 처리 중 오류: {e}")

    def run(self, iterations: int | None = None) -> None:
        """iterations=None 이면 무한 루프. 테스트 시에는 정수를 넘겨 제한 실행."""
        self.notifier.info(
            f"트레이더 시작: {self.exchange.name} / 전략={self.strategy.name} / 마켓={self.markets}"
        )
        count = 0
        try:
            while iterations is None or count < iterations:
                self.step()
                count += 1
                if iterations is None or count < iterations:
                    time.sleep(self.poll_seconds)
        except KeyboardInterrupt:
            self.notifier.info("트레이더 종료 (사용자 중단)")
