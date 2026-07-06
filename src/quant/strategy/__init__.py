from quant.strategy.base import Signal, Strategy
from quant.strategy.ma_momentum import MaMomentumStrategy
from quant.strategy.mean_reversion import MeanReversionStrategy
from quant.strategy.volatility_breakout import VolatilityBreakoutStrategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "volatility_breakout": VolatilityBreakoutStrategy,
    "ma_momentum": MaMomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
}

__all__ = [
    "Signal",
    "Strategy",
    "VolatilityBreakoutStrategy",
    "MaMomentumStrategy",
    "MeanReversionStrategy",
    "STRATEGY_REGISTRY",
]
