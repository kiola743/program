"""한국투자증권 KIS Developers API 어댑터 (스텁).

ExchangeAdapter 인터페이스를 그대로 구현하면 전략/백테스트/리스크/트레이더 코드는
수정 없이 한국주식 매매에 재사용할 수 있다. 실제 REST 연동은 아직 미구현.

구현 시 참고:
- 인증: OAuth2 접근토큰 발급 (KIS_APP_KEY, KIS_APP_SECRET) 후 매 요청 헤더에 첨부,
  토큰은 24시간 유효하므로 캐싱 필요.
- get_ohlcv: 국내주식기간별시세(일/주/월/년) API, 분봉은 국내주식분봉조회 API.
- buy_market/sell_market: 국내주식 주문 API는 지정가 위주이므로 시장가 주문 시
  최우선호가로 지정가 주문하는 방식으로 근사 필요.
- round_qty: 주식은 1주 단위(정수)로 내림 처리해야 함 -> 아래 오버라이드 참고.
- is_market_open: 한국 정규장 09:00~15:30 (공휴일 캘린더 별도 필요), 주말/공휴일 제외.
"""

from __future__ import annotations

from datetime import datetime, time

import pandas as pd

from quant.exchange.base import Balance, ExchangeAdapter, OrderResult

MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)


class KisExchange(ExchangeAdapter):
    name = "kis"

    def __init__(self, app_key: str = "", app_secret: str = "", account_no: str = ""):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no

    def get_current_price(self, market: str) -> float:
        raise NotImplementedError("KIS 실시간 시세 연동은 아직 구현되지 않았습니다")

    def get_ohlcv(self, market: str, interval: str = "day", count: int = 200) -> pd.DataFrame:
        raise NotImplementedError("KIS 일봉/분봉 조회는 아직 구현되지 않았습니다")

    def get_cash(self) -> float:
        raise NotImplementedError("KIS 예수금 조회는 아직 구현되지 않았습니다")

    def get_position(self, market: str) -> Balance | None:
        raise NotImplementedError("KIS 보유잔고 조회는 아직 구현되지 않았습니다")

    def buy_market(self, market: str, krw_amount: float) -> OrderResult:
        raise NotImplementedError("KIS 매수 주문은 아직 구현되지 않았습니다")

    def sell_market(self, market: str, qty: float) -> OrderResult:
        raise NotImplementedError("KIS 매도 주문은 아직 구현되지 않았습니다")

    def is_market_open(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        if now.weekday() >= 5:  # 토(5)/일(6)
            return False
        return MARKET_OPEN <= now.time() <= MARKET_CLOSE

    def round_qty(self, market: str, qty: float) -> float:
        return float(int(qty))  # 주식은 1주 단위
