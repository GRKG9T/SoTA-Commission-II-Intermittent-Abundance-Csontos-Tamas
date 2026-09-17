"""
control/strategies/fixed_reserve.py -- Strategy 2: Fixed reserve

The simplest "smart" (state-dependent) strategy: it needs no forecast.
Every hour it simply checks the BESS's current state of charge, and if it
falls below the fixed threshold (config.FIXED_RESERVE_FRACTION, e.g. 20%),
it fully shuts down the electrolyzer and the DAC -- regardless of
whether the sun will shine tomorrow or not.

This is the simplest genuine "insurance": you always pay the premium (the
lost production time) whenever the state of charge is below the threshold
-- even if the sun comes out again within the hour.
"""

from control.strategies.base_strategy import BaseStrategy


class FixedReserveStrategy(BaseStrategy):
    name = "fixed_reserve"
    display_name = "2. Fixed Reserve"
    complexity = 1
    needs_forecast = False

    def decide(self, current_hour: int, system_state: dict) -> dict:
        pv_kw = system_state["pv_power_kw"]
        bess_soc_kwh = system_state["bess_soc_kwh"]

        threshold_kwh = self.bess_min_soc_kwh + self.reserve_fraction * self.bess_capacity_kwh
        active = bess_soc_kwh < threshold_kwh

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
