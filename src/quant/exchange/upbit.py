"""업비트 어댑터.

공개 시세(get_ohlcv, get_current_price)는 API 키 없이 동작한다.
잔고 조회와 주문은 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 가 필요하다.
"""

from __future__ import annotations

import pandas as pd
import pyupbit

from quant.exchange.base import Balance, ExchangeAdapter, OrderResult

UPBIT_FEE_PCT = 0.0005  # KRW 마켓 0.05%


class UpbitExchange(ExchangeAdapter):
    name = "upbit"

    def __init__(self, access_key: str = "", secret_key: str = ""):
        self._client = pyupbit.Upbit(access_key, secret_key) if access_key and secret_key else None

    def _require_client(self) -> pyupbit.Upbit:
        if self._client is None:
            raise RuntimeError(
                "업비트 API 키가 설정되지 않았습니다. .env 에 UPBIT_ACCESS_KEY / "
                "UPBIT_SECRET_KEY 를 입력하세요. (백테스트/페이퍼는 키 없이 동작합니다)"
            )
        return self._client

    # ----- 시세 (공개 API) -----
    def get_current_price(self, market: str) -> float:
        price = pyupbit.get_current_price(market)
        if price is None:
            raise ConnectionError(f"{market} 현재가 조회 실패 (네트워크/API 오류)")
        return float(price)

    def get_ohlcv(self, market: str, interval: str = "day", count: int = 200) -> pd.DataFrame:
        df = pyupbit.get_ohlcv(market, interval=interval, count=count)
        if df is None or df.empty:
            raise ConnectionError(f"{market} 캔들 조회 실패 (네트워크/API 오류)")
        return df[["open", "high", "low", "close", "volume"]]

    # ----- 계좌 (인증 필요) -----
    def get_cash(self) -> float:
        return float(self._require_client().get_balance("KRW") or 0.0)

    def get_position(self, market: str) -> Balance | None:
        client = self._require_client()
        currency = market.split("-")[1]  # KRW-BTC -> BTC
        for b in client.get_balances():
            if b["currency"] == currency:
                qty = float(b["balance"]) + float(b["locked"])
                if qty <= 0:
                    return None
                return Balance(market=market, qty=qty, avg_price=float(b["avg_buy_price"]))
        return None

    # ----- 주문 (인증 필요) -----
    def buy_market(self, market: str, krw_amount: float) -> OrderResult:
        client = self._require_client()
        resp = client.buy_market_order(market, krw_amount)
        if not resp or "uuid" not in resp:
            raise RuntimeError(f"{market} 시장가 매수 실패: {resp}")
        price = self.get_current_price(market)
        fee = krw_amount * UPBIT_FEE_PCT
        qty = (krw_amount - fee) / price
        return OrderResult(market=market, side="buy", price=price, qty=qty,
                           krw_amount=krw_amount - fee, fee=fee)

    def sell_market(self, market: str, qty: float) -> OrderResult:
        client = self._require_client()
        resp = client.sell_market_order(market, qty)
        if not resp or "uuid" not in resp:
            raise RuntimeError(f"{market} 시장가 매도 실패: {resp}")
        price = self.get_current_price(market)
        gross = qty * price
        fee = gross * UPBIT_FEE_PCT
        return OrderResult(market=market, side="sell", price=price, qty=qty,
                           krw_amount=gross - fee, fee=fee)
