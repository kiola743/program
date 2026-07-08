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
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS trader_state (
                key TEXT PRIMARY KEY, value TEXT
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

    # ----- 트레이더 상태 KV (재시작해도 트레일링 스탑 고점 등을 유지) -----
    def set_state(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO trader_state (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def get_state(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM trader_state WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else None

    def delete_state(self, key: str) -> None:
        self._conn.execute("DELETE FROM trader_state WHERE key=?", (key,))
        self._conn.commit()

    def daily_summary(self, exchange_name: str, day_iso: str) -> dict:
        """해당 일자(YYYY-MM-DD)의 체결/손익 요약 (일일 리포트용)."""
        trades = self._conn.execute(
            "SELECT side, COUNT(*), COALESCE(SUM(krw_amount),0) FROM trade_log "
            "WHERE exchange=? AND ts LIKE ? GROUP BY side",
            (exchange_name, f"{day_iso}%"),
        ).fetchall()
        by_side = {side: {"count": cnt, "krw": krw} for side, cnt, krw in trades}
        equity_row = self._conn.execute(
            "SELECT equity, cash FROM equity_log WHERE exchange=? ORDER BY ts DESC LIMIT 1",
            (exchange_name,),
        ).fetchone()
        return {
            "buy_count": by_side.get("buy", {}).get("count", 0),
            "sell_count": by_side.get("sell", {}).get("count", 0),
            "buy_krw": by_side.get("buy", {}).get("krw", 0.0),
            "sell_krw": by_side.get("sell", {}).get("krw", 0.0),
            "equity": equity_row[0] if equity_row else None,
            "cash": equity_row[1] if equity_row else None,
        }
