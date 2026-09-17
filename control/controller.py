"""
control/controller.py -- "Life insurance" controller (LifeInsuranceController)

This is the project's main control logic: this module is what distinguishes
the proactive simulation (smart_sim.py) from the naive baseline (baseline_sim.py).

The single, decisive difference between the two controllers:
    - The baseline looks only at the current hour's actual PV production --
      it has no lookahead, so it only reacts after the deficit has already
      occurred.
    - This controller projects, every single hour, what would happen to the
      BESS state of charge over the next threshold_hours hours if we only
      covered the reactor's maintenance need from PV/BESS. If this projected
      trajectory would ever fall below the safety minimum (min_soc), it
      activates "life insurance" mode: before the deficit actually occurs,
      it shuts down the electrolyzer and the DAC (so that all PV surplus
      can go toward charging the BESS), and reserves a buffer to protect
      the reactor.

Why project the BESS trajectory, and not just count the raw "production <
demand" hours? We tried two simpler variants along the way, and each had a
serious flaw:
    1. If we only count the hours where production is below the
       maintenance level (maintenance_kw), then every night shows up as a
       "deficit" -- since production is always 0 at night. This resulted
       in life insurance mode being active almost all the time, even on
       the nicest summer days.
    2. If we look at the net balance over the entire forecast window (e.g.
       7 days) (daytime surpluses offset against nighttime deficits), then
       over a longer window we can almost always find a good enough day for
       the net balance to come out positive -- which meant the mechanism
       almost never activated, not even as genuine, multi-day overcast
       periods approached.
Projecting the BESS state-of-charge trajectory ("what would happen to my
storage if, from this point on, I only tried to keep the reactor
maintained") solves both problems: it accounts for the fact that the BESS's
current state of charge is already a kind of buffer (a well-charged BESS can
ride out plenty of ordinary nights with no concern at all), and it also
catches it if the trajectory would dip dangerously low at any intermediate
point (not just at the end), even if the energy balance would look "fine on
average" at the end of the whole period.
"""

import numpy as np


class LifeInsuranceController:
    """The proactive, forecast-based reactor-protection controller."""

    def __init__(
        self,
        threshold_hours: int,
        reserve_fraction: float,
        forecast_pv_kw,
        bess_capacity_kwh: float,
        bess_min_soc: float,
        bess_max_soc: float,
        maintenance_kw: float,
        coldstart_kw: float,
        tau_hours: float,
        electrolyzer_min_kw: float,
    ):
        self.threshold_hours = threshold_hours
        self.reserve_fraction = reserve_fraction
        self.forecast_pv_kw = forecast_pv_kw  # the full (known) PV time series -- used as a "perfect" forecast
        self.bess_capacity_kwh = bess_capacity_kwh
        self.bess_min_soc_kwh = bess_min_soc * bess_capacity_kwh
        self.bess_max_soc_kwh = bess_max_soc * bess_capacity_kwh
        self.maintenance_kw = maintenance_kw
        self.coldstart_kw = coldstart_kw
        self.tau_hours = tau_hours
        self.electrolyzer_min_kw = electrolyzer_min_kw

    def _calculate_deficit(self, forecast_window, current_soc_kwh: float) -> float:
        """
        Projects the BESS state-of-charge trajectory for the coming hours,
        under the (deliberately simplified) assumption that every hour we
        only try to cover the reactor's maintenance need (maintenance_kw)
        from PV/BESS -- the other consumers (electrolyzer, DAC) only ever
        use PV surplus anyway, so they don't affect whether the BESS drops
        to a dangerous level.

        The "danger zone" boundary is drawn not at the physical minimum
        (min_soc), but reserve_fraction*capacity higher than that -- this
        is the "safety margin": the larger the reserve_fraction, the
        earlier/more sensitively the controller detects trouble, and the
        larger the buffer it tries to work with (more activations, fewer
        cold starts -- but also more lost production time. This is the
        exact trade-off that step 9's parameter sweep will map out.)

        Returns: how far below the safety threshold (min_soc +
        reserve_fraction*capacity) the projected trajectory's lowest point
        would fall -- 0 if the trajectory would never drop below it.
        """
        safety_floor_kwh = self.bess_min_soc_kwh + self.reserve_fraction * self.bess_capacity_kwh

        net_flow_per_hour = np.asarray(forecast_window, dtype=float) - self.maintenance_kw
        projected_soc_kwh = current_soc_kwh + np.cumsum(net_flow_per_hour)
        # The BESS cannot charge above its physical maximum -- without this,
        # after a very sunny stretch the model would overestimate the
        # buffer available for a subsequent overcast period.
        projected_soc_kwh = np.clip(projected_soc_kwh, None, self.bess_max_soc_kwh)

        projected_min_kwh = float(projected_soc_kwh.min()) if len(projected_soc_kwh) > 0 else current_soc_kwh
        return max(0.0, safety_floor_kwh - projected_min_kwh)

    def _calculate_reserve_needed(self, deficit_kwh: float, tau_hours: float) -> float:
        """
        The energy needed to keep the reactor warm, based on the expected
        deficit. Because of the cooling time constant (tau), the reactor
        does not immediately need active heating the moment production
        drops below the maintenance level: the heat already accumulated
        keeps the temperature up on its own for a while (roughly
        tau_hours hours). We subtract this "grace period" (worth
        maintenance_kw * tau_hours of energy) from the total deficit -- so
        that we don't reserve more buffer than is actually needed.
        """
        grace_kwh = self.maintenance_kw * tau_hours
        return max(0.0, deficit_kwh - grace_kwh)

    def decide(self, current_hour: int, system_state: dict) -> dict:
        """
        One hour's worth of decision-making.

        current_hour: the index of the current hour (index into the
                       forecast_pv_kw sequence).
        system_state keys:
            pv_power_kw:               the current hour's actual PV production
            reactor_state:              the reactor's current ReactorState
            bess_soc_kwh:               the BESS's current state of charge [kWh]
            bess_discharge_available_kw: how much the BESS could output right
                                          now (per physical limits, computed
                                          without any reserve)

        Returns a command_dict with the same keys that RTULayer.arbitrate()
        expects, plus a "life_insurance_active" flag field (the latter is
        only used for logging/metrics -- the RTU doesn't care about it).
        """
        # threshold_hours is the lookahead length: how many hours ahead
        # we look when projecting the BESS trajectory. The longer it is,
        # the earlier (the more distant a danger it can detect) the
        # protection can activate -- but it can also cause more (possibly
        # needlessly early) activations, if the more distant forecast is
        # less certain.
        window_end = min(current_hour + self.threshold_hours, len(self.forecast_pv_kw))
        forecast_window = self.forecast_pv_kw[current_hour:window_end]

        deficit_kwh = self._calculate_deficit(forecast_window, system_state["bess_soc_kwh"])
        life_insurance_active = deficit_kwh > 0

        # The actually-needed reserve, derived from the deficit -- reduced
        # by the tau_hours "grace period" (see _calculate_reserve_needed).
        # This value is only used for logging/metrics (see smart_sim.py).
        reserve_kwh = self._calculate_reserve_needed(deficit_kwh, self.tau_hours) if life_insurance_active else 0.0

        pv_kw = system_state["pv_power_kw"]
        reactor_state = system_state["reactor_state"]
        total_available_kw = pv_kw + system_state["bess_discharge_available_kw"]

        if life_insurance_active:
            # We proactively shut down the industrial consumers now,
            # before the deficit actually occurs, so that all PV
            # surplus goes toward charging the BESS/building the reserve.
            electrolyzer_command = "off"
            dac_command = "off"
        else:
            electrolyzer_command = "on"
            dac_command = "on"

        # The reactor's state-dependent decision -- the same logic as the
        # baseline (see simulation/baseline_sim.py), with the difference
        # that here a pre-reserved buffer may also be available for the
        # maintenance need.
        can_produce = pv_kw >= self.electrolyzer_min_kw

        if reactor_state.value in ("operating", "maintenance"):
            if can_produce:
                reactor_command = "operate"
            elif total_available_kw >= self.maintenance_kw:
                reactor_command = "maintain"
            else:
                reactor_command = "shutdown"
        else:  # cold or cold_start
            if total_available_kw >= self.coldstart_kw:
                reactor_command = "operate"
            elif total_available_kw >= self.maintenance_kw:
                reactor_command = "maintain"
            else:
                reactor_command = "shutdown"

        return {
            "life_insurance_active": life_insurance_active,
            "reserve_kwh": reserve_kwh,
            "electrolyzer_command": electrolyzer_command,
            "dac_command": dac_command,
            "reactor_command": reactor_command,
        }
