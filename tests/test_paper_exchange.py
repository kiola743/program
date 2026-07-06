from unittest.mock import patch

import pytest

from quant.exchange.paper import PaperExchange


@pytest.fixture
def exchange(tmp_path):
    return PaperExchange(initial_cash=1_000_000, db_path=tmp_path / "test.db")


def test_initial_cash(exchange):
    assert exchange.get_cash() == 1_000_000
    assert exchange.get_position("KRW-BTC") is None


@patch("quant.exchange.paper.pyupbit.get_current_price", return_value=100_000_000.0)
def test_buy_then_sell_roundtrip(mock_price, exchange):
    buy = exchange.buy_market("KRW-BTC", 100_000)
    assert buy.side == "buy"
    assert exchange.get_cash() == pytest.approx(900_000)
    pos = exchange.get_position("KRW-BTC")
    assert pos is not None
    assert pos.qty == pytest.approx(buy.qty)

    sell = exchange.sell_market("KRW-BTC", pos.qty)
    assert sell.side == "sell"
    assert exchange.get_position("KRW-BTC") is None
    # 왕복 수수료로 인해 최초 현금보다 약간 적어야 함
    assert exchange.get_cash() < 1_000_000


@patch("quant.exchange.paper.pyupbit.get_current_price", return_value=100_000_000.0)
def test_buy_rejects_insufficient_cash(mock_price, exchange):
    with pytest.raises(ValueError):
        exchange.buy_market("KRW-BTC", 2_000_000)


@patch("quant.exchange.paper.pyupbit.get_current_price", return_value=100_000_000.0)
def test_sell_rejects_insufficient_qty(mock_price, exchange):
    exchange.buy_market("KRW-BTC", 100_000)
    pos = exchange.get_position("KRW-BTC")
    with pytest.raises(ValueError):
        exchange.sell_market("KRW-BTC", pos.qty * 2)
