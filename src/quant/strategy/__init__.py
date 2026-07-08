from quant.strategy.abs_momentum import AbsoluteMomentumStrategy
from quant.strategy.base import Signal, Strategy
from quant.strategy.donchian import DonchianBreakoutStrategy
from quant.strategy.ma_momentum import MaMomentumStrategy
from quant.strategy.mean_reversion import MeanReversionStrategy
from quant.strategy.volatility_breakout import VolatilityBreakoutStrategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "volatility_breakout": VolatilityBreakoutStrategy,
    "ma_momentum": MaMomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "donchian": DonchianBreakoutStrategy,
    "abs_momentum": AbsoluteMomentumStrategy,
}

__all__ = [
    "Signal",
    "Strategy",
    "VolatilityBreakoutStrategy",
    "MaMomentumStrategy",
    "MeanReversionStrategy",
    "DonchianBreakoutStrategy",
    "AbsoluteMomentumStrategy",
    "STRATEGY_REGISTRY",
]
