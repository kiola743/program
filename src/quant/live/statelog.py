"""거래소 종류(paper/live) 무관 공용 상태 로그.

트레이더가 매 스텝마다 자산 스냅샷을, 매 체결마다 거래 내역을 기록해두면
대시보드는 거래소 어댑터 내부 구현을 몰라도 이 두 테이블만 읽어 현재 상태를
그릴 수 있다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from quant.exchange.base import OrderResult


class StateLog:
    def __init__(self, db_path: str | Path = "data/quant.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS trade_log (
                ts TEXT, exchange TEXT, market TEXT, side TEXT,
                price REAL, qty REAL, krw_amount REAL, fee REAL
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS equity_log (
                ts TEXT, exchange TEXT, equity REAL, cash REAL
            )"""
        )
        self._conn.commit()

    def record_trade(self, exchange_name: str, result: OrderResult) -> None:
        self._conn.execute(
            "INSERT INTO trade_log VALUES (?,?,?,?,?,?,?,?)",
            (result.ts.isoformat(), exchange_name, result.market, result.side,
             result.price, result.qty, result.krw_amount, result.fee),
        )
        self._conn.commit()

    def record_equity(self, exchange_name: str, equity: float, cash: float) -> None:
        self._conn.execute(
            "INSERT INTO equity_log VALUES (?,?,?,?)",
            (datetime.now().isoformat(), exchange_name, equity, cash),
        )
        self._conn.commit()
