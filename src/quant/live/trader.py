"""실시간 매매 루프. paper/live 어댑터 공용 — 어댑터 구현체만 교체하면 된다.

동작: poll_seconds 주기로 각 마켓의 최근 캔들을 가져와 전략 시그널을 확인하고,
리스크 매니저 승인 하에 매수/매도하며, 매 체결과 에러를 디스코드로 알린다.

매 루프마다 시그널과 별개로 확인하는 안전장치:
- 고정 손절 (진입가 대비 stop_loss_pct 하락)
- 트레일링 스탑 (진입 후 최고가 대비 trailing_stop_pct 하락) — 고점은 SQLite에
  영속화되어 프로세스를 재시작해도 유지된다
- 레짐 필터 (BTC가 장기 이평 아래면 신규 매수 금지)
- 일일 손실 한도 kill switch (RiskManager)

날짜(KST 기준 로컬 날짜)가 바뀌면 전일 요약 리포트를 디스코드로 전송한다.
"""

from __future__ import annotations

import logging
import time
from datetime import date

from quant.exchange.base import ExchangeAdapter
from quant.live.statelog import StateLog
from quant.notify.discord import DiscordNotifier
from quant.risk.manager import RiskManager, compute_atr_pct
from quant.strategy.base import Signal, Strategy
from quant.strategy.regime import latest_regime_ok

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
        regime_cfg: dict | None = None,
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
        self.regime_cfg = regime_cfg or {}
        self._today = date.today()

    # ----- 상태 헬퍼 -----
    def _hwm_key(self, market: str) -> str:
        return f"hwm:{self.exchange.name}:{market}"

    def _get_hwm(self, market: str) -> float:
        if self.state_log is None:
            return 0.0
        value = self.state_log.get_state(self._hwm_key(market))
        return float(value) if value else 0.0

    def _update_hwm(self, market: str, price: float) -> float:
        hwm = max(self._get_hwm(market), price)
        if self.state_log is not None:
            self.state_log.set_state(self._hwm_key(market), str(hwm))
        return hwm

    def _clear_hwm(self, market: str) -> None:
        if self.state_log is not None:
            self.state_log.delete_state(self._hwm_key(market))

    def _total_equity(self) -> float:
        equity = self.exchange.get_cash()
        for m in self.markets:
            pos = self.exchange.get_position(m)
            if pos:
                equity += pos.qty * self.exchange.get_current_price(m)
        return equity

    # ----- 리스크 확인 -----
    def _check_protective_stops(self, market: str) -> None:
        """고정 손절 + 트레일링 스탑. 시그널과 무관하게 매 루프 확인."""
        pos = self.exchange.get_position(market)
        if pos is None:
            return
        price = self.exchange.get_current_price(market)
        hwm = self._update_hwm(market, price)

        if self.risk.should_stop_loss(pos.avg_price, price):
            self.notifier.info(
                f"{market} 손절 조건 도달 (진입가 {pos.avg_price:,.0f} -> 현재가 {price:,.0f})"
            )
            self._sell(market, pos.qty)
        elif self.risk.should_trailing_stop(hwm, price):
            self.notifier.info(
                f"{market} 트레일링 스탑 발동 (고점 {hwm:,.0f} -> 현재가 {price:,.0f})"
            )
            self._sell(market, pos.qty)

    def _regime_allows_buy(self) -> bool:
        if not self.regime_cfg.get("enabled"):
            return True
        base_market = self.regime_cfg.get("market", "KRW-BTC")
        ma_period = int(self.regime_cfg.get("ma_period", 200))
        try:
            base_df = self.exchange.get_ohlcv(base_market, interval="day",
                                              count=ma_period + 5)
            return latest_regime_ok(base_df, ma_period)
        except Exception:
            logger.exception("레짐 판정 실패 — 보수적으로 매수 금지")
            return False

    # ----- 주문 -----
    def _sell(self, market: str, qty: float) -> None:
        pos = self.exchange.get_position(market)
        result = self.exchange.sell_market(market, qty)
        self.notifier.trade(str(result))
        self._clear_hwm(market)
        if self.state_log:
            self.state_log.record_trade(self.exchange.name, result)
        if pos:
            pnl = (result.price - pos.avg_price) * result.qty - result.fee
            self.risk.record_realized_pnl(pnl, self._total_equity())

    def _buy(self, market: str, df) -> None:
        equity = self._total_equity()
        cash = self.exchange.get_cash()
        ok, reason = self.risk.can_place_buy(equity, cash)
        if not ok:
            self.notifier.info(f"{market} 매수 보류: {reason}")
            return
        if not self._regime_allows_buy():
            self.notifier.info(f"{market} 매수 보류: 하락 레짐 (BTC가 장기 이평 아래)")
            return

        atr_pct = compute_atr_pct(df, self.risk.atr_period)
        amount = self.risk.size_order_krw(equity, cash, atr_pct)
        if amount < self.risk.min_order_krw:
            self.notifier.info(
                f"{market} 매수 보류: 변동성 반영 주문금액({amount:,.0f}원)이 최소 주문금액 미만"
            )
            return
        result = self.exchange.buy_market(market, amount)
        self.notifier.trade(str(result))
        self._update_hwm(market, result.price)
        if self.state_log:
            self.state_log.record_trade(self.exchange.name, result)

    # ----- 일일 리포트 -----
    def _send_daily_report_if_new_day(self) -> None:
        today = date.today()
        if today == self._today:
            return
        prev_day = self._today
        self._today = today
        if self.state_log is None:
            return
        try:
            summary = self.state_log.daily_summary(self.exchange.name, prev_day.isoformat())
            equity_str = f"{summary['equity']:,.0f}원" if summary["equity"] is not None else "-"
            positions = []
            for m in self.markets:
                pos = self.exchange.get_position(m)
                if pos:
                    positions.append(f"{m} {pos.qty:.8f}")
            self.notifier.info(
                f"**일일 리포트 ({prev_day.isoformat()})**\n"
                f"매수 {summary['buy_count']}건 ({summary['buy_krw']:,.0f}원) / "
                f"매도 {summary['sell_count']}건 ({summary['sell_krw']:,.0f}원)\n"
                f"현재 총자산: {equity_str}\n"
                f"보유: {', '.join(positions) if positions else '없음'}"
            )
        except Exception:
            logger.exception("일일 리포트 전송 실패")

    # ----- 메인 루프 -----
    def step(self) -> None:
        """한 주기 실행 (테스트 용이성을 위해 run()에서 분리)."""
        self._send_daily_report_if_new_day()
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
                self._check_protective_stops(market)
                df = self.exchange.get_ohlcv(market, interval=self.interval, count=self.lookback)
                signal = self.strategy.latest_signal(df)
                pos = self.exchange.get_position(market)

                if signal == Signal.BUY and pos is None:
                    self._buy(market, df)
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
