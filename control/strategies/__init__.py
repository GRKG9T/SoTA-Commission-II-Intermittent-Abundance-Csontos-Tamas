"""
control/strategies -- the 7 BESS control strategies being compared.

ALL_STRATEGIES: the list of strategy classes, always in this order (this is
the same order that appears on the charts too, from simplest to most
complex).
"""

from control.strategies.base_strategy import BaseStrategy
from control.strategies.fixed_reserve import FixedReserveStrategy
from control.strategies.forecast_binary import ForecastBinaryStrategy
from control.strategies.precharge import PrechargeStrategy
from control.strategies.proportional_reserve import ProportionalReserveStrategy
from control.strategies.reactive_baseline import ReactiveBaselineStrategy
from control.strategies.rolling_horizon import RollingHorizonStrategy
from control.strategies.temperature_based import TemperatureBasedStrategy

ALL_STRATEGIES = [
    ReactiveBaselineStrategy,
    FixedReserveStrategy,
    ForecastBinaryStrategy,
    ProportionalReserveStrategy,
    TemperatureBasedStrategy,
    PrechargeStrategy,
    RollingHorizonStrategy,
]

__all__ = [
    "BaseStrategy",
    "ReactiveBaselineStrategy",
    "FixedReserveStrategy",
    "ForecastBinaryStrategy",
    "ProportionalReserveStrategy",
    "TemperatureBasedStrategy",
    "PrechargeStrategy",
    "RollingHorizonStrategy",
    "ALL_STRATEGIES",
]
