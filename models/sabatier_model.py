"""
models/sabatier_model.py -- Sabatier reactor thermal state machine

This is the project's most critical model: it decides when the reactor
cools down (and thus when a 4-6 hour cold start becomes necessary), and
this is exactly what we want to avoid with proactive BESS control.

Cooling equation (Newton's law of cooling):
    T(t+1) = T_env + (T(t) - T_env) * exp(-dt / tau)
where "tau" is the cooling time constant [hours], "T_env" is the
outside (ambient) temperature. Every simulation step is 1 hour (dt = 1),
the project as a whole works in hourly steps.

Important simplification (see also section 9.1 of the documentation):
this model only calculates cooling with the formula above -- the effect
of maintenance heating is not modelled with a continuous differential
equation, but as a simpler rule: if there is enough power for
maintenance, the temperature can never fall below min_temp (the heating
"holds" it there); if there isn't enough power, the reactor cools freely
according to the formula above.

States (ReactorState):
    OPERATING   -- normal operation, producing, temperature = operating_temp
    MAINTENANCE -- maintenance mode, heating power = maintenance_kw,
                   not producing, temperature >= min_temp
    COLD_START  -- cold start in progress, high power demand
                   (coldstart_kw), not producing
    COLD        -- cooled down (temperature < min_temp), restart required
"""

import math
from enum import Enum


class ReactorState(str, Enum):
    """Also derived from str, so that when written to CSV/DataFrame it
    stays readable text (e.g. 'operating'), not just a Python object."""

    OPERATING = "operating"
    MAINTENANCE = "maintenance"
    COLD_START = "cold_start"
    COLD = "cold"


class SabatierModel:
    """Simplified thermal state machine of the Sabatier reactor."""

    def __init__(
        self,
        min_temp: float,
        operating_temp: float,
        tau_hours: float,
        maintenance_kw: float,
        coldstart_kw: float,
        coldstart_hours: float,
    ):
        self.min_temp = min_temp
        self.operating_temp = operating_temp
        self.tau_hours = tau_hours
        self.maintenance_kw = maintenance_kw
        self.coldstart_kw = coldstart_kw
        self.coldstart_hours = coldstart_hours

        # The reactor is already warmed up and in operating state at the
        # start of the simulation -- a reasonable starting point for a
        # new annual simulation.
        self.state = ReactorState.OPERATING
        self.temperature_c = float(operating_temp)
        self._coldstart_hours_remaining = 0.0

    def _cool(self, env_temp_c: float) -> float:
        """Applies one hour's (dt = 1) worth of Newtonian cooling to the
        current temperature, without accounting for any heating/maintenance."""
        dt = 1.0
        return env_temp_c + (self.temperature_c - env_temp_c) * math.exp(-dt / self.tau_hours)

    def step(self, available_power_kw: float, env_temp_c: float, command: str) -> dict:
        """
        Executes one hourly step.

        available_power_kw: the power [kW] that can be allocated to the
                             reactor (for maintenance or cold start).
        env_temp_c:          the outside (ambient) temperature [C] in
                              this hour -- this is the "T_env" in the
                              cooling formula.
        command:              "operate"  -- should produce / return to operation
                               "maintain" -- maintenance mode (not producing)
                               "shutdown" -- no power, free cooling

        Returns a dict:
            state:               ReactorState -- the new state
            temperature_c:       float -- the new temperature
            power_consumed_kw:   float -- power actually consumed this hour
            is_producing:        bool -- whether it is producing this hour (only under OPERATING)
            coldstart_triggered: bool -- whether a new cold start started
                                  this hour (this is the most important
                                  metric we want to minimize!)
        """
        if command not in ("operate", "maintain", "shutdown"):
            raise ValueError(
                f"Invalid command: {command!r}. Valid values: 'operate', 'maintain', 'shutdown'."
            )

        if command == "operate":
            return self._handle_operate()
        elif command == "maintain":
            return self._handle_maintain(available_power_kw, env_temp_c)
        else:
            return self._handle_shutdown(env_temp_c)

    def _handle_operate(self) -> dict:
        coldstart_triggered = False

        if self.state == ReactorState.OPERATING:
            # Already operating -- the Sabatier reaction is exothermic and
            # self-sustaining, no additional power is needed for this state.
            power_consumed_kw = 0.0

        elif self.state == ReactorState.MAINTENANCE:
            # Was within the maintainable range (temperature >= min_temp) ->
            # immediately returns to operating temperature, without a cold
            # start. This is the essence of the whole "life insurance"
            # strategy: if we managed to keep the reactor warm, there is
            # no loss.
            self.state = ReactorState.OPERATING
            self.temperature_c = float(self.operating_temp)
            power_consumed_kw = 0.0

        else:
            # From the COLD state -- a new cold start begins (or one
            # already in progress continues). This is the most important
            # event in the project: this is what we want to minimize.
            if self.state != ReactorState.COLD_START:
                coldstart_triggered = True
                self.state = ReactorState.COLD_START
                self._coldstart_hours_remaining = float(self.coldstart_hours)

            power_consumed_kw = self.coldstart_kw
            self._coldstart_hours_remaining -= 1.0

            # Simplified, linear ramp-up curve from min_temp to
            # operating_temp -- the documentation does not prescribe an
            # exact temperature curve during cold start, only the
            # duration (coldstart_hours) and the coldstart_triggered flag.
            progress = 1.0 - (self._coldstart_hours_remaining / self.coldstart_hours)
            progress = min(max(progress, 0.0), 1.0)
            self.temperature_c = self.min_temp + (self.operating_temp - self.min_temp) * progress

            if self._coldstart_hours_remaining <= 0:
                self.state = ReactorState.OPERATING
                self.temperature_c = float(self.operating_temp)

        return self._build_result(power_consumed_kw, coldstart_triggered)

    def _handle_maintain(self, available_power_kw: float, env_temp_c: float) -> dict:
        self._coldstart_hours_remaining = 0.0  # a cold start in progress gets interrupted

        cooled_temp = self._cool(env_temp_c)
        has_enough_power = available_power_kw >= self.maintenance_kw

        if self.state != ReactorState.COLD and has_enough_power:
            # Still within the maintainable range, and there is enough
            # power for heating -- the temperature cannot fall below min_temp.
            self.temperature_c = max(cooled_temp, self.min_temp)
            power_consumed_kw = self.maintenance_kw
        else:
            # Either already cold (the maintenance heater is not strong
            # enough to reheat a cooled-down reactor), or there is not
            # enough power -- it keeps cooling freely.
            self.temperature_c = cooled_temp
            power_consumed_kw = 0.0

        self.state = ReactorState.MAINTENANCE if self.temperature_c >= self.min_temp else ReactorState.COLD
        return self._build_result(power_consumed_kw, coldstart_triggered=False)

    def _handle_shutdown(self, env_temp_c: float) -> dict:
        self._coldstart_hours_remaining = 0.0  # a cold start in progress gets interrupted
        self.temperature_c = self._cool(env_temp_c)
        self.state = ReactorState.MAINTENANCE if self.temperature_c >= self.min_temp else ReactorState.COLD
        return self._build_result(power_consumed_kw=0.0, coldstart_triggered=False)

    def _build_result(self, power_consumed_kw: float, coldstart_triggered: bool) -> dict:
        return {
            "state": self.state,
            "temperature_c": self.temperature_c,
            "power_consumed_kw": power_consumed_kw,
            "is_producing": self.state == ReactorState.OPERATING,
            "coldstart_triggered": coldstart_triggered,
        }


# =============================================================================
# Standalone run: verification of step 4 per the documentation
#   "Test: cools down from 400C with a 6-hour tau, calculates how many
#    hours it takes to fall below 300C. This is the most critical
#    model -- it needs the most testing."
# =============================================================================
if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import config

    ENV_TEMP_C = 15.0  # ambient temperature used for the test -- not part of config.py,
    # because in the real simulation this comes hourly from the weather data (T2m).

    print("Sabatier thermal model verification\n")
    print(
        f"Parameters: min_temp={config.SABATIER_MIN_TEMP_C} C, "
        f"operating_temp={config.SABATIER_OPERATING_TEMP_C} C, "
        f"tau={config.SABATIER_TAU_HOURS} hours, ambient temperature={ENV_TEMP_C} C\n"
    )

    # --- Test 1: free cooling -- how many hours until it falls below 300 C? ---
    print("--- Test 1: free cooling (shutdown command, no heating) ---")
    reactor = SabatierModel(
        min_temp=config.SABATIER_MIN_TEMP_C,
        operating_temp=config.SABATIER_OPERATING_TEMP_C,
        tau_hours=config.SABATIER_TAU_HOURS,
        maintenance_kw=config.SABATIER_MAINTENANCE_KW,
        coldstart_kw=config.SABATIER_COLDSTART_KW,
        coldstart_hours=config.SABATIER_COLDSTART_HOURS,
    )
    hours_to_cold = None
    for hour in range(1, 25):
        r = reactor.step(available_power_kw=0, env_temp_c=ENV_TEMP_C, command="shutdown")
        print(f"  hour {hour}: T={r['temperature_c']:.1f} C, state={r['state'].value}")
        if r["state"] == ReactorState.COLD and hours_to_cold is None:
            hours_to_cold = hour
            break

    # Analytical check based on the same formula (not via the step-by-step
    # simulation, but solving the continuous-time formula directly):
    #   T(t) = T_env + (T0 - T_env) * exp(-t/tau)  =>  t = -tau * ln((Ttarget-T_env)/(T0-T_env))
    t_analytical = -config.SABATIER_TAU_HOURS * math.log(
        (config.SABATIER_MIN_TEMP_C - ENV_TEMP_C) / (config.SABATIER_OPERATING_TEMP_C - ENV_TEMP_C)
    )
    print(
        f"\n  The reactor fell below 300 C during full hour {hours_to_cold}. "
        f"(From the analytical formula, the exact crossing time is: {t_analytical:.2f} hours,"
        f" which falls between the discrete hour {hours_to_cold} and hour {hours_to_cold - 1} -- as expected.)"
    )
    assert hours_to_cold - 1 < t_analytical < hours_to_cold, "The discrete and analytical results should agree!"
    print("  OK: the simulation agrees with the analytical Newton's-law formula.\n")

    # --- Test 2: maintenance keeps the temperature at min_temp ---
    print("--- Test 2: maintenance mode (enough energy available for heating) ---")
    reactor2 = SabatierModel(
        min_temp=config.SABATIER_MIN_TEMP_C,
        operating_temp=config.SABATIER_OPERATING_TEMP_C,
        tau_hours=config.SABATIER_TAU_HOURS,
        maintenance_kw=config.SABATIER_MAINTENANCE_KW,
        coldstart_kw=config.SABATIER_COLDSTART_KW,
        coldstart_hours=config.SABATIER_COLDSTART_HOURS,
    )
    for hour in range(1, 13):
        r = reactor2.step(
            available_power_kw=config.SABATIER_MAINTENANCE_KW,  # exactly enough energy
            env_temp_c=ENV_TEMP_C,
            command="maintain",
        )
        if hour in (1, 2, 3, 6, 12):
            print(f"  hour {hour}: T={r['temperature_c']:.1f} C, state={r['state'].value}, power={r['power_consumed_kw']:.0f} kW")
    assert abs(reactor2.temperature_c - config.SABATIER_MIN_TEMP_C) < 0.1, "After 12 hours of maintenance it should be sitting at min_temp!"
    print(f"  OK: after 12 hours of maintenance the temperature sits stably at {reactor2.temperature_c:.1f} C (= min_temp), never fell below it.\n")

    # --- Test 3: life insurance pays off -- no cold start after maintenance ---
    print("--- Test 3: 'life insurance' -- a maintained reactor returns immediately, no cold start ---")
    r = reactor2.step(available_power_kw=0, env_temp_c=ENV_TEMP_C, command="operate")
    print(
        f"  'operate' command to the maintained reactor -> state={r['state'].value}, "
        f"producing={r['is_producing']}, cold_start={r['coldstart_triggered']}"
    )
    assert r["coldstart_triggered"] is False and r["is_producing"] is True, "A maintained reactor should not trigger a cold start!"
    print("  OK: there was no cold start -- this is exactly the payoff of the proactive strategy.\n")

    # --- Test 4: actual cold start -- a fully cooled-down reactor, how long does it take? ---
    print("--- Test 4: actual cold start on a fully cooled-down reactor ---")
    reactor3 = SabatierModel(
        min_temp=config.SABATIER_MIN_TEMP_C,
        operating_temp=config.SABATIER_OPERATING_TEMP_C,
        tau_hours=config.SABATIER_TAU_HOURS,
        maintenance_kw=config.SABATIER_MAINTENANCE_KW,
        coldstart_kw=config.SABATIER_COLDSTART_KW,
        coldstart_hours=config.SABATIER_COLDSTART_HOURS,
    )
    for _ in range(24):  # let it cool down completely
        reactor3.step(available_power_kw=0, env_temp_c=ENV_TEMP_C, command="shutdown")
    print(f"  Starting point: state={reactor3.state.value}, T={reactor3.temperature_c:.1f} C")

    coldstart_hours_used = 0
    for hour in range(1, 15):
        r = reactor3.step(available_power_kw=config.SABATIER_COLDSTART_KW, env_temp_c=ENV_TEMP_C, command="operate")
        coldstart_hours_used += 1
        if hour == 1:
            assert r["coldstart_triggered"] is True, "The first 'operate' call should trigger the cold start!"
        if r["is_producing"]:
            break
    print(
        f"  The cold start finished in {coldstart_hours_used} hours "
        f"(per config: {config.SABATIER_COLDSTART_HOURS} hours), final T={r['temperature_c']:.1f} C, "
        f"state={r['state'].value}"
    )
    assert coldstart_hours_used == config.SABATIER_COLDSTART_HOURS, "The cold start should take exactly coldstart_hours hours!"
    print("  OK: the cold start took exactly the configured duration, and finished in the OPERATING state.")
