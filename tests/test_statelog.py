from datetime import datetime

from quant.exchange.base import OrderResult
from quant.live.statelog import StateLog


def test_record_trade_and_equity(tmp_path):
    log = StateLog(db_path=tmp_path / "state.db")
    result = OrderResult(market="KRW-BTC", side="buy", price=90_000_000.0,
                         qty=0.001, krw_amount=90_000.0, fee=45.0, ts=datetime.now())
    log.record_trade("paper", result)
    log.record_equity("paper", equity=1_000_000.0, cash=910_000.0)

    import sqlite3
    conn = sqlite3.connect(tmp_path / "state.db")
    trades = conn.execute("SELECT market, side, exchange FROM trade_log").fetchall()
    equity_rows = conn.execute("SELECT exchange, equity, cash FROM equity_log").fetchall()

    assert trades == [("KRW-BTC", "buy", "paper")]
    assert equity_rows == [("paper", 1_000_000.0, 910_000.0)]
