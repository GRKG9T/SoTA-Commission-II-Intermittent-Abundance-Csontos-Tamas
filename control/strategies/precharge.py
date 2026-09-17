"""
control/strategies/precharge.py -- Strategy 6: Precharge strategy

The other strategies (3., 4., 5.) decide based on a computed deficit --
i.e. they only kick in once the forecast indicates the maintenance need
would actually be endangered. This strategy reacts earlier and more
cautiously: it already activates once the forecast average PV production
over the next threshold_hours hours falls below
config.PRECHARGE_TRIGGER_FRACTION (e.g. 40%) of the nominal PV capacity --
even if no actual deficit can formally be computed from that yet.

When activated, it does more than reserve a buffer: it fully shuts down
the electrolyzer and the DAC as well (not just limiting them to the
portion above the reserve, as strategies 3./4./5. do), so that all PV
surplus can go toward charging the BESS before the deficit actually
occurs. This is expected to be most useful in Scotland (the cloudiest
site), where "sunny minutes" are rare and valuable -- here they must not be
carelessly squandered on electrolysis/DAC when an overcast period is
approaching.
"""

import numpy as np

from control.strategies.base_strategy import BaseStrategy


class PrechargeStrategy(BaseStrategy):
    name = "precharge"
    display_name = "6. Precharge"
    complexity = 3
    needs_forecast = True

    def decide(self, current_hour: int, system_state: dict) -> dict:
        pv_kw = system_state["pv_power_kw"]

        window = self._forecast_window(current_hour)
        mean_forecast_kw = float(np.mean(window)) if len(window) > 0 else 0.0
        active = mean_forecast_kw < self.precharge_trigger_fraction * self.pv_capacity_kw

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
