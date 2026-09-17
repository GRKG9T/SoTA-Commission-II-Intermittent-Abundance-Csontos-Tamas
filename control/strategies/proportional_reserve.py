"""
control/strategies/proportional_reserve.py -- Strategy 4: Proportional reserve

Decides in two steps, sitting halfway between the binary (3.) and the
rolling-horizon (7.) strategy:

    1. From a simple, aggregated deficit signal (the same one used by
       strategy 3), it estimates a severity (between 0 and 1, relative to
       the BESS's total capacity), and from this it linearly interpolates a
       reserve fraction between config.PROPORTIONAL_MIN_RESERVE_FRACTION and
       config.PROPORTIONAL_MAX_RESERVE_FRACTION: small deficit -> small
       reserve, large deficit -> large reserve.
    2. With this (severity-adjusted) safety margin, it projects the BESS
       state-of-charge trajectory hour by hour (the same mechanism as the
       rolling-horizon (7.) strategy), except there the margin is fixed,
       whereas here it adapts to the severity of the expected deficit.

This way the reserve size genuinely matters (not just an on/off switch as
in strategy 3): a more severe deficit produces a larger margin, and
therefore protection that activates earlier and more sensitively.
"""

import numpy as np

from control.strategies.base_strategy import BaseStrategy


class ProportionalReserveStrategy(BaseStrategy):
    name = "proportional_reserve"
    display_name = "4. Proportional Reserve"
    complexity = 3
    needs_forecast = True

    def decide(self, current_hour: int, system_state: dict) -> dict:
        pv_kw = system_state["pv_power_kw"]
        window = self._forecast_window(current_hour)

        # 1. Severity -> proportional reserve fraction.
        simple_deficit_kwh = self._net_balance_deficit(window)
        severity = min(1.0, simple_deficit_kwh / self.bess_capacity_kwh) if self.bess_capacity_kwh > 0 else 0.0
        reserve_fraction = self.min_reserve_fraction + severity * (
            self.max_reserve_fraction - self.min_reserve_fraction
        )

        # 2. Trajectory projection with this margin (see rolling_horizon.py's
        # identical mechanism -- here the margin isn't fixed, but severity-dependent).
        safety_floor_kwh = self.bess_min_soc_kwh + reserve_fraction * self.bess_capacity_kwh
        net_flow_per_hour = np.asarray(window, dtype=float) - self.maintenance_kw
        projected_soc_kwh = system_state["bess_soc_kwh"] + np.cumsum(net_flow_per_hour)
        projected_soc_kwh = np.clip(projected_soc_kwh, None, self.bess_max_soc_kwh)
        projected_min_kwh = (
            float(projected_soc_kwh.min()) if len(projected_soc_kwh) > 0 else system_state["bess_soc_kwh"]
        )

        active = projected_min_kwh < safety_floor_kwh

        reactor_command, reactor_reserved_kw = self._decide_reactor(
            pv_kw, system_state["reactor_state"], system_state["total_available_kw"]
        )

        return {
            "life_insurance_active": active,
            "reserve_kwh": reserve_fraction * self.bess_capacity_kwh,
            "electrolyzer_command": "off" if active else "on",
            "dac_command": "off" if active else "on",
            "reactor_command": reactor_command,
            "reactor_reserved_kw": reactor_reserved_kw,
        }
