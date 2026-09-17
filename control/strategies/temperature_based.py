"""
control/strategies/temperature_based.py -- Strategy 5: Temperature-based

The "smartest" (most physically well-founded) strategy: instead of
reserving a fixed or proportionally scaled %, it calculates from the
physics how much energy would be needed to keep the reactor at the minimum
for the full duration of the expected deficit, subtracting the "free"
natural cooling grace period afforded by the current temperature:

    t_grace = tau * ln((T_current - T_env) / (T_min - T_env))     [hours]
    E_reserve = maintenance_kw * max(0, deficit_hours - t_grace)  [kWh]

Based on Newton's law of cooling, t_grace expresses how long it would take
for the reactor to cool down on its own (without heating) from its current
temperature to the minimum -- up to that point heating isn't needed, so no
reserve is needed for that time. After that, however, the maintenance power
must be paid for the remainder of the deficit, which is why E_reserve
multiplies the maintenance power by "deficit_hours - t_grace" (the heating
time still remaining after the grace period), not by t_grace itself.

Note: this formula was inverted in the project's earlier version. The
first implementation computed E_reserve = maintenance_kw * t_grace,
meaning the hotter the reactor (the larger the t_grace grace period), the
larger a reserve it reserved, and when the reactor was already at the
minimum (t_grace=0, the most dangerous state), the formula produced 0 kWh
of reserve -- it protected nothing exactly when protection was needed
most. Empirical test (Seville, full year): the reserve activated in only 4
out of 8760 hours, and the computed value was almost always 0 (the reactor,
in the maintenance state, already reaches and then stays at min_temp within
~2 hours, per the cooling formula -- see models/sabatier_model.py's
_handle_maintain()). In the fixed direction, the formula behaves the
opposite way, as is physically sensible: if the reactor is already cold
(t_grace=0), a reserve is needed for the full expected deficit duration
(maximum protection); if it is still hot (large t_grace), little or no
reserve is needed (natural cooling will carry it through most of the
deficit anyway).

The "expected deficit duration" (deficit_hours) is simplified to be equal
to the length of the forecast window (self.threshold_hours) -- the same
window that strategies 3./4. also use to detect a deficit.

The strategy decides in two steps: (1) does the forecast (using the same
net-balance formula as strategies 3./4.) indicate any deficit at all -- if
not, computing the formula would be pointless, since the reactor in
"normal" operation is already warm anyway (T_current close to
operating_temp), and in that case the formula would also come out empty
(0 reserve); (2) if so, it computes the formula above, and compares the
current BESS state of charge against this computed threshold -- only fully
shutting down the electrolyzer/DAC if the state of charge is already below
the threshold.
"""

import numpy as np

from control.strategies.base_strategy import BaseStrategy


class TemperatureBasedStrategy(BaseStrategy):
    name = "temperature_based"
    display_name = "5. Temperature-Based"
    complexity = 4
    needs_forecast = True

    def decide(self, current_hour: int, system_state: dict) -> dict:
        pv_kw = system_state["pv_power_kw"]

        window = self._forecast_window(current_hour)
        deficit_kwh = self._net_balance_deficit(window)
        active = deficit_kwh > 0

        if active:
            t_current = system_state["reactor_temperature_c"]
            t_env = system_state["env_temp_c"]

            # Guarding against the log's invalid domain (<=0): if the
            # reactor is already at or below the minimum, or if the
            # ambient temperature somehow ended up above the minimum,
            # there is no meaningful "how much longer would it last
            # naturally" time.
            numerator = max(t_current - t_env, 1e-6)
            denominator = max(self.min_temp - t_env, 1e-6)
            ratio = max(numerator / denominator, 1.0 + 1e-9)
            t_grace_hours = self.tau_hours * np.log(ratio)

            # The remaining (post-grace-period) heating time, from the full
            # length of the expected deficit (the forecast window) -- this
            # is what actually requires a reserve.
            deficit_duration_hours = float(len(window))
            reserve_kwh = self.maintenance_kw * max(0.0, deficit_duration_hours - t_grace_hours)
            reserve_kwh = min(max(reserve_kwh, 0.0), self.bess_capacity_kwh)

            # We compare the current state of charge against the threshold
            # computed from the formula -- we only fully switch off the
            # industrial consumers if the BESS has actually already dropped
            # below it.
            threshold_kwh = self.bess_min_soc_kwh + reserve_kwh
            active = system_state["bess_soc_kwh"] < threshold_kwh
        else:
            reserve_kwh = 0.0

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
