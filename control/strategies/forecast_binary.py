"""
control/strategies/forecast_binary.py -- Strategy 3: Forecast-driven binary

Every hour it looks at the forecast energy balance for the next
threshold_hours hours. If the forecast deficit > 0 (using the net-balance
formula already built in step 8 -- see base_strategy.py
_net_balance_deficit()): protection switches on, with a fixed-size reserve
(config.RESERVE_FRACTION). If not: protection is fully switched off, and
the BESS is freely usable.

This is simpler than the proportional (4.) or the rolling-horizon (7.)
strategy: it doesn't scale the reserve size to the severity of the deficit,
and it doesn't project the full BESS trajectory -- it just compares one
number (the total deficit) against one threshold.

When activated, it fully shuts down the electrolyzer and the DAC (not
just "limits" them) -- see control/strategies/base_strategy.py's
explanation of why this (full shutdown, leaving more PV surplus for the
BESS) is the only mechanism that works here.
"""

from control.strategies.base_strategy import BaseStrategy


class ForecastBinaryStrategy(BaseStrategy):
    name = "forecast_binary"
    display_name = "3. Forecast Binary"
    complexity = 2
    needs_forecast = True

    def decide(self, current_hour: int, system_state: dict) -> dict:
        pv_kw = system_state["pv_power_kw"]

        window = self._forecast_window(current_hour)
        deficit_kwh = self._net_balance_deficit(window)
        active = deficit_kwh > 0

        reactor_command, reactor_reserved_kw = self._decide_reactor(
            pv_kw, system_state["reactor_state"], system_state["total_available_kw"]
        )

        return {
            "life_insurance_active": active,
            "reserve_kwh": (self.reserve_fraction * self.bess_capacity_kwh) if active else 0.0,
            "electrolyzer_command": "off" if active else "on",
            "dac_command": "off" if active else "on",
            "reactor_command": reactor_command,
            "reactor_reserved_kw": reactor_reserved_kw,
        }
