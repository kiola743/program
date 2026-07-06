"""페이퍼 트레이딩 어댑터.

실시간 시세(업비트 공개 API)로 가상 체결을 수행한다. API 키 불필요.
실계좌에 영향을 주지 않으므로 live 전환 전 검증 단계로 사용한다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pyupbit

from quant.exchange.base import Balance, ExchangeAdapter, OrderResult

FEE_PCT = 0.0005


class PaperExchange(ExchangeAdapter):
    name = "paper"

    def __init__(self, initial_cash: float, db_path: str | Path = "data/quant.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._init_db(initial_cash)

    def _init_db(self, initial_cash: float) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS paper_cash (id INTEGER PRIMARY KEY CHECK (id=1), krw REAL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS paper_position "
            "(market TEXT PRIMARY KEY, qty REAL, avg_price REAL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS paper_trades "
            "(ts TEXT, market TEXT, side TEXT, price REAL, qty REAL, krw_amount REAL, fee REAL)"
        )
        cur.execute("INSERT OR IGNORE INTO paper_cash (id, krw) VALUES (1, ?)", (initial_cash,))
        self._conn.commit()

    def get_current_price(self, market: str) -> float:
        price = pyupbit.get_current_price(market)
        if price is None:
            raise ConnectionError(f"{market} 현재가 조회 실패")
        return float(price)

    def get_ohlcv(self, market: str, interval: str = "day", count: int = 200) -> pd.DataFrame:
        df = pyupbit.get_ohlcv(market, interval=interval, count=count)
        if df is None or df.empty:
            raise ConnectionError(f"{market} 캔들 조회 실패")
        return df[["open", "high", "low", "close", "volume"]]

    def get_cash(self) -> float:
        row = self._conn.execute("SELECT krw FROM paper_cash WHERE id=1").fetchone()
        return float(row[0])

    def _set_cash(self, krw: float) -> None:
        self._conn.execute("UPDATE paper_cash SET krw=? WHERE id=1", (krw,))
        self._conn.commit()

    def get_position(self, market: str) -> Balance | None:
        row = self._conn.execute(
            "SELECT qty, avg_price FROM paper_position WHERE market=?", (market,)
        ).fetchone()
        if row is None or row[0] <= 0:
            return None
        return Balance(market=market, qty=row[0], avg_price=row[1])

    def _log_trade(self, r: OrderResult) -> None:
        self._conn.execute(
            "INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?)",
            (r.ts.isoformat(), r.market, r.side, r.price, r.qty, r.krw_amount, r.fee),
        )
        self._conn.commit()

    def buy_market(self, market: str, krw_amount: float) -> OrderResult:
        cash = self.get_cash()
        if krw_amount > cash:
            raise ValueError(f"현금 부족: 주문 {krw_amount:,.0f}원 > 보유 {cash:,.0f}원")
        price = self.get_current_price(market)
        fee = krw_amount * FEE_PCT
        qty = (krw_amount - fee) / price

        pos = self.get_position(market)
        if pos is None:
            new_qty, new_avg = qty, price
        else:
            new_qty = pos.qty + qty
            new_avg = (pos.qty * pos.avg_price + qty * price) / new_qty
        self._conn.execute(
            "INSERT INTO paper_position (market, qty, avg_price) VALUES (?,?,?) "
            "ON CONFLICT(market) DO UPDATE SET qty=excluded.qty, avg_price=excluded.avg_price",
            (market, new_qty, new_avg),
        )
        self._set_cash(cash - krw_amount)
        result = OrderResult(market=market, side="buy", price=price, qty=qty,
                             krw_amount=krw_amount - fee, fee=fee)
        self._log_trade(result)
        return result

    def sell_market(self, market: str, qty: float) -> OrderResult:
        pos = self.get_position(market)
        if pos is None or qty > pos.qty + 1e-12:
            held = pos.qty if pos else 0.0
            raise ValueError(f"보유 수량 부족: 매도 {qty} > 보유 {held}")
        price = self.get_current_price(market)
        gross = qty * price
        fee = gross * FEE_PCT
        net = gross - fee

        remaining = pos.qty - qty
        if remaining <= 1e-12:
            self._conn.execute("DELETE FROM paper_position WHERE market=?", (market,))
        else:
            self._conn.execute(
                "UPDATE paper_position SET qty=? WHERE market=?", (remaining, market)
            )
        self._set_cash(self.get_cash() + net)
        result = OrderResult(market=market, side="sell", price=price, qty=qty,
                             krw_amount=net, fee=fee)
        self._log_trade(result)
        return result
