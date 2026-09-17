"""
control/strategies/rolling_horizon.py -- Strategy 7: Rolling horizon

The most sophisticated strategy: this is the same logic as
control/controller.py's LifeInsuranceController, which the project built
earlier (in step 8), moved over onto the new, common strategy interface.

Instead of deciding from a single number (the whole window's net balance,
as strategies 3./4./5. do), it projects the BESS state-of-charge trajectory
hour by hour for the next threshold_hours hours, and finds the trajectory's
lowest point. If this point would fall below the safety threshold (min_soc
+ reserve_fraction * capacity), protection activates -- and the reserve
size is exactly the difference between the threshold and the projected
minimum, reduced by the cooling "grace period" (tau_hours *
maintenance_kw -- see control/controller.py's original explanation).

This catches cases where the deficit is most severe in the middle of the
window (not just looking at the summed final result), so it handles
forecast error the best -- but it performs a full trajectory calculation
every hour (not just a single summation), which makes it the most
computationally demanding strategy.

When activated -- just like the precharge (6.) strategy -- it fully
shuts down the electrolyzer and the DAC.
"""

import numpy as np

from control.strategies.base_strategy import BaseStrategy


class RollingHorizonStrategy(BaseStrategy):
    name = "rolling_horizon"
    display_name = "7. Rolling Horizon"
    complexity = 5
    needs_forecast = True

    def decide(self, current_hour: int, system_state: dict) -> dict:
        pv_kw = system_state["pv_power_kw"]
        window = self._forecast_window(current_hour)

        safety_floor_kwh = self.bess_min_soc_kwh + self.reserve_fraction * self.bess_capacity_kwh

        net_flow_per_hour = np.asarray(window, dtype=float) - self.maintenance_kw
        projected_soc_kwh = system_state["bess_soc_kwh"] + np.cumsum(net_flow_per_hour)
        projected_soc_kwh = np.clip(projected_soc_kwh, None, self.bess_max_soc_kwh)
        projected_min_kwh = float(projected_soc_kwh.min()) if len(projected_soc_kwh) > 0 else system_state["bess_soc_kwh"]

        deficit_kwh = max(0.0, safety_floor_kwh - projected_min_kwh)
        active = deficit_kwh > 0

        grace_kwh = self.maintenance_kw * self.tau_hours
        reserve_kwh = max(0.0, deficit_kwh - grace_kwh) if active else 0.0

        reactor_command, reactor_reserved_kw = self._decide_reactor(
            pv_kw, system_state["reactor_state"], system_state["total_available_kw"]
        )

        return {
            "life_insurance_active": active,
            "reserve_kwh": reserve_kwh,
            "electrolyzer_command": "off" if active else "on",
            "dac_command": "off" if active else "on",
            "reactor_command": reactor_command,
            "reactor_reserved_kw": reactor_reserved_kw,
        }
