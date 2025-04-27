"""
Battery Controller and State Machine module.

Module to control, monitor and keep track of the charge/discharging cycles for
a Li-Ion battery.

The charge and discharge currents, and battery voltage is monitored via one or
more ADS1115_ ADC modules.

The charging and discharging is managed by a TP4056_ BMS, for which the input
and output is switched from digital IO pins on the MCU (`Wemos S2 Mini`_ in this
case), via some MOSFETs.

Required external libs:
    * ads1x15_ - Library forked from Robert Hammelrath's ads1x15 lib for
      MicroPython

.. _ADS1115: https://components101.com/modules/ads1115-module-with-programmable-gain-amplifier
.. _TP4056: https://components101.com/modules/tp4056a-li-ion-battery-chargingdischarging-module
.. _Wemos S2 Mini: https://www.wemos.cc/en/latest/s2/s2_mini.html
.. _ads1x15: http://gitlab.gaul.za/tomc/micropython-ads1x15
"""

import uasyncio as asyncio
import utime as time
from lib import ulogging as logging
from lib.adc_monitor import VoltageMonitor, ChargeMonitor
from lib.statemachines import (  # pylint: disable=unused-import
    BCStateMachine,
    SoCStateMachine,
    # We do not use this import here, but we import it as a convenience for the
    # telemetry module that will use it.
    telemetry_trigger,
)
from lib.utils import genBatteryID

from i2c_config import Pin
from config import (
    ads1115,
    ADC_SAMPLE_RATE,
    V_SPIKE_TH,
    V_SPIKE_TH_T,
    C_SPIKE_TH,
    C_SPIKE_TH_T,
    D_SPIKE_TH,
    D_SPIKE_TH_T,
    C_VOLTAGE_TH,
    D_VOLTAGE_TH,
)

from structures import ADCChannel, SpikeDetectCFG


class BatteryController(BCStateMachine):
    """
    A Battery Controller based on the `BCStateMachine` for managing and
    controlling these modules.

    A **BC** consists of the following:

    * Battery **Voltage** monitor:
        * This is a `VoltageMonitor` instance that monitors the battery voltage
          and also detects spikes in this voltage level, which are assumed to
          corresponds to the inserting or removing the battery - `_v_mon`.
    * Battery **Charging** control and monitor:
        * An IO Pin connected to the charge activation MOSFET (see the
          **Schematic** section in `config` for details). Setting this pin high
          switches the MOSFET on and starts the battery charging - `_pin_ch`.
        * A `ChargeMonitor` that monitors the charge current and amount of
          change for a given charge cycle - `_ch_mon`.
    * Battery **Discharging** control and monitor:
        * An IO Pin connected to the discharge activation MOSFET (see the
          **Schematic** section in `config` for details). Setting this pin high
          switches the MOSFET on and starts the battery discharging - `_pin_dch`.
        * A `ChargeMonitor` that monitors the discharge current and amount of
          change for a given charge cycle - `_dch_mon`.

    On instantiation, the monitor task (`ADCMonitor._monitor`) for each of the
    three ADC monitors will be created, but the charge/discharge monitors will
    both be paused, while only the voltage monitor will be running.

    Both charge and discharge switches will also be set off.

    As the three monitors described above sees changes in voltage or current,
    they will call back to internal functions (`_voltageSpike`, `_chargeSpike`,
    `_dischargeSpike`) which will then make a `transition()` call for the type
    of change event detected. This may change the controller state if the event
    is valid.

    Other external interfaces allows for other state changes - see `setID`,
    `charge`, `discharge`, `pause`, `resume`, `resetMetrics` and `reset` for
    more details.

    The current controller state can be checked by various other attributes and
    methods: `BCStateMachine.state`, `bat_v`, `bat_id`, `charge_vals`, `discharge_vals`.

    Attributes:

        _bc_prefix: Used as logging prefix to distinguish log messages by
            `BatteryController`
        _pin_ch: Charge control pin
        _pin_dch: Discharge control pin
        _bat_id: This will be the ID given to the battery currently being
            monitored by this controller.
        _v_mon: A `VoltageMonitor` as described above to monitor the battery
            voltage.
        _ch_mon: A `ChargeMonitor` as described above to monitor battery
            charging.
        _dch_mon: A `ChargeMonitor` as described above to monitor battery
            discharging.
    """

    # Do not worry @pylint: disable=too-many-instance-attributes

    def __init__(self, name: str, v_cfg: tuple, ch_cfg: tuple, dch_cfg: tuple):
        """
        Instance initializer to set up a new `BatteryController` given the
        hardware config for it.

        The ``hw_conf`` argument is one of the elements from `HARDWARE_CFG` and
        describes the full config for one controller. See `HARDWARE_CFG` for more
        details on the structure.

        Each of the `VoltageMonitor`, and the two `ChargeMonitor` s that are set up
        will check the given ADC address against the available ADCs in
        `AVAILABLE_ADCS`. If the given address is not available, or the given
        channel is invalid, the monitor will be disabled.

        If any monitor is disabled, then the `BatteryController` instance's
        ``disable`` field will be ``True`` and the ``reason`` field will have a
        reason for being disabled. All other monitors for this controller will
        then also be set to disabled.

        As of now, we automatically set up spike detection on the
        `VoltageMonitor`, `_v_mon` only. We use the `V_SPIKE_TH` and
        `V_SPIKE_TH_T` spike threshold values from ``config.py`` - see
        `SpikeDetectCFG` for more info. The `_voltageSpike` callback will be
        called when voltage spikes (battery insert / remove) was detected.

        Note that asyncio monitor task for each of the monitors that are not
        disabled would also have been started, and will start running as soon
        as the asyncio scheduler starts running.

        Args:
            name: The controller name from `HARDWARE_CFG`
            v_cfg: The voltage monitor config from `HARDWARE_CFG` for this
                controller.
            ch_cfg: The charge monitor config from `HARDWARE_CFG` for this
                controller.
            dch_cfg: The discharge monitor config from `HARDWARE_CFG` for this
                controller.

        Raises:
            Any number of Exceptions on invalid input.
        """
        # Call up
        super().__init__(name)

        # Used for logging
        self._bc_prefix: str = f"{self.name} (BC)"

        # The charge and discharge control pins
        self._pin_ch: Pin = Pin(ch_cfg[0], Pin.OUT, value=0)  # Charge control pin
        self._pin_dch: Pin = Pin(dch_cfg[0], Pin.OUT, value=0)  # Discharge control pin

        # This will be the ID given to the battery currently in the holder.
        self._bat_id: str = ""

        # Create a Battery voltage monitor instance
        self._v_mon = VoltageMonitor(
            ads1115,
            ADCChannel(addr=v_cfg[0], chan=v_cfg[1]),
            ADC_SAMPLE_RATE,
            avg_w=v_cfg[2],
            spike_cfg=SpikeDetectCFG(
                V_SPIKE_TH, V_SPIKE_TH_T, self._voltageSpike, False, True
            ),
        )
        # Create a Charging monitor instance
        self._ch_mon = ChargeMonitor(
            ads1115,
            ADCChannel(addr=ch_cfg[1], chan=ch_cfg[2]),
            ADC_SAMPLE_RATE,
            shunt=ch_cfg[3],
            avg_w=ch_cfg[4],
            spike_cfg=SpikeDetectCFG(
                C_SPIKE_TH, C_SPIKE_TH_T, self._chargeSpike, False, True
            ),
        )
        # Create a Discharging monitor instance
        self._dch_mon = ChargeMonitor(
            ads1115,
            ADCChannel(addr=dch_cfg[1], chan=dch_cfg[2]),
            ADC_SAMPLE_RATE,
            shunt=dch_cfg[3],
            avg_w=dch_cfg[4],
            spike_cfg=SpikeDetectCFG(
                D_SPIKE_TH, D_SPIKE_TH_T, self._dischargeSpike, False, True
            ),
        )
        # Determine if the controller will be disable or not, depending if any of
        # the monitors are disabled.
        if any(m._disabled for m in (self._v_mon, self._ch_mon, self._dch_mon)):
            self.transition(self.E_disable)
            self.soc_m = None
            # Do not do anything further
            return

        # Not disabled, so we can transition to the initialized state.
        self.transition(self.E_init)

        # Set up a State of Charge monitor state machine
        self.soc_m = SoCStateMachine(self)

    def __str__(self) -> str:
        """
        String representation of the instance.

        Returns:
            The BC name and state
        """
        return f"[BC::{self.name}] ({self.state_name})"

    @property
    def bat_v(self) -> int:
        """
        Property to return the current battery voltage.

        Returns:
            The battery voltage in mV.
        """
        return self._v_mon.voltage

    @property
    def bat_id(self) -> int:
        """
        Property to return the current battery ID.
        """
        return self._bat_id

    @property
    def charge_vals(self) -> tuple:
        """
        Property to return the current charging values as a tuple:

        * 0 - Shunt resistor (R) value in ohm
        * 1 - Voltage in mV (filtered)
        * 2 - Current in mA (filtered)
        * 3 - Charge in mC (filtered)
        * 4 - Used charge in mAh (filtered)
        * 5 - Charge time in seconds


        Return:
            (RΩ, mV, mA, mC, mAh, tm)
        """
        return (
            self._ch_mon._shunt,  # pylint: disable=protected-access
            self._ch_mon.voltage,
            self._ch_mon.current,
            self._ch_mon.charge,
            self._ch_mon.mAh,
            round(self._ch_mon.charge_time / 1000),
        )

    @property
    def discharge_vals(self) -> tuple:
        """
        Property to return the current discharging values:

        * 0 - Shunt resistor (R) value in ohm
        * 1 - Voltage in mV (filtered)
        * 2 - Current in mA (filtered)
        * 3 - Charge in mC (filtered)
        * 4 - Used charge in mAh (filtered)
        * 5 - Charge time in seconds


        Return:
            (RΩ, mV, mA, mC, mAh, tm)
        """
        return (
            self._dch_mon._shunt,  # pylint: disable=protected-access
            self._dch_mon.voltage,
            self._dch_mon.current,
            self._dch_mon.charge,
            self._dch_mon.mAh,
            round(self._dch_mon.charge_time / 1000),
        )

    def transition(self, event: int) -> bool:
        """
        Overrides the `BCStateMachine.transition` method so we can apply certain
        actions on successful transitions.

        Returns:
            True if the transition was successful, False otherwise.
        """
        # We do have many return statements and branches here so
        # @pylint: disable=too-many-return-statements,too-many-branches

        # Call up and return False if the transition is not accepted.
        if not super().transition(event):
            return False

        # Now we apply the various actions based on the new state.

        if self.state == self.S_DISABLED:
            # Switch off controllers
            self._cdControl(state=False, ch=True, dch=True)
            # Disable monitors
            for m in (self._v_mon, self._ch_mon, self._dch_mon):
                m._disabled = True  # pylint: disable=protected-access

        # Make sure both charging and discharge if off when we get to the NO
        # Battery state
        if self.state == self.S_NOBAT:
            # Reset the battery ID and switch off both charger and discharger
            self._bat_id = ""
            self._cdControl(state=False, ch=True, dch=True)
            return True

        # Do we now have a battery inserted, but no ID?
        if self.state == self.S_BAT_NOID:
            if self.transition(self.E_get_id):
                # Generate a new default unique battery ID.
                self._bat_id = genBatteryID()
                logging.info(
                    "%s: New battery inserted. Auto transitioned to waiting for ID",
                    self._bc_prefix,
                )
            else:
                logging.error(
                    "%s: Unable to auto transitioned to waiting for ID on new battery insert.",
                    self._bc_prefix,
                )
                return False

        # As soon as get a new ID for a newly inserted battery, we reset all
        # old monitors.
        if self.state == self.S_BAT_ID:
            self._resetMonitors()
            # Nothing failed here ,so we return True
            return True

        # When we transitioned to charging, we need to switch the controller on
        if self.state == self.S_CHARGE:
            # NOTE: If our FSM is correct we should not ever get an error here.
            return self._cdControl(state=True, ch=True)

        # When we transitioned to charging paused or completed, we need to
        # switch the controller off
        if self.state in (self.S_CHARGE_PAUSE, self.S_CHARGED):
            return self._cdControl(state=False, ch=True)

        # When we transitioned to discharging, we need to switch the controller
        # on.
        if self.state == self.S_DISCHARGE:
            # First start the discharge monitor
            asyncio.create_task(self._dischargeMonitor())
            # NOTE: If our FSM is correct we should not ever get an error here.
            return self._cdControl(state=True, dch=True)

        # When we transitioned to discharging paused or completed, we need to
        # switch the controller off
        if self.state in (self.S_DISCHARGE_PAUSE, self.S_DISCHARGED):
            if self.S_DISCHARGED:
                # When discharged, the battery would effectively have been
                # disconnected by the DW01 on the TP4056 board. This means that the
                # last voltage seen by the v_mon was higher than our V_SPIKE_TH,
                # and the next v_mon spike detection will take us straight to the
                # yanked state which we do not want. To avoid this, we reset the
                # v_mon here.
                self._v_mon.reset()
            return self._cdControl(state=False, dch=True)

        # Was the battery yanked?
        if self.state == self.S_YANKED:
            # Switch off both controllers
            return self._cdControl(state=False, ch=True, dch=True)

        return True

    def _cdControl(self, state: bool, ch: bool = False, dch: bool = False) -> bool:
        """
        Charge and discharge control.

        This is a private method to be called on a successful transition to and
        from certain states.

        It controls the charging/discharging MOSFETs and monitors and allows
        charging/discharging to be started or stopped.

        Note:
            Switching **off** (state==False) can be done for **ch** and **dch**
            at the same time, but switching **on** can only be done for one or
            the other, since we can never allow charging and discharging to
            happen simultaneously.

        Args:
            state: True to switch **on**, False to switch **off**.
            ch: True if charging state should be changed. See note above.
            dch: True if discharging state should be changed. See note above.

        Returns:
            True if successful, False on error, with an error message logged.
        """
        if not (ch or dch):
            logging.error(
                "%s _cdControl: both ch and dch is False. Nothing to switch",
                self._bc_prefix,
            )
            return False

        # We can not switch both controllers on
        if state and ch and dch:
            logging.error(
                "%s _cdControl: Can not switch on ch and dch simultaneously.",
                self._bc_prefix,
            )
            return False

        # At this point we have one or both controllers to switch off, or only
        # one of them to switch on.
        # Cycle over both target controllers and monitors and also pass in the
        # other controller pin and:
        for ctl, mon, pin_t, pin_o in (
            (ch, self._ch_mon, self._pin_ch, self._pin_dch),
            (dch, self._dch_mon, self._pin_dch, self._pin_ch),
        ):
            # Switching off is easy
            if not state:
                # Should this controller be switched off?
                if ctl:
                    # Switch off the MOSFET using the target pin and pause the
                    # monitor.
                    pin_t.value(0)
                    mon.pause()
                # We are switching off, so we can continue on to the next.
                continue

            # We get here if we need to switch on. If this controller is not to
            # be switched continue on to the next
            if not ctl:
                continue

            # We can only switch the target on if the other is off.
            if pin_o.value():
                logging.error(
                    "%s _cdControl: Can not switch on ch or dch while "
                    "the other is already on.",
                    self._bc_prefix,
                )
                # Since we already know that only one of the two will be
                # switched on, we can return with an error here.
                return False

            # All good, do it.
            pin_t.value(1)
            mon.resume()

        return True

    def _voltageSpike(self, jump: bool, v_from: bool, v_to: bool):
        """
        Callback for when a battery voltage spike was detected.

        The spike threshold is set by `V_SPIKE_TH` and this is either for a
        jump or drop.

        Args:
            jump: Will be True if this was a jump, False if it was a drop.
            v_from: The value from which the jump occurred
            v_to: The value to which the jump occurred.
        """
        logging.info(
            "%s: Voltage spike detected: %s (%s -> %s = %sv)",
            self._bc_prefix,
            "jump" if jump else "drop",
            v_from,
            v_to,
            v_to - v_from,
        )
        # Update the state if possible
        if not self.transition(self.E_v_jump if jump else self.E_v_drop):
            logging.error(
                "%s: State transition not valid for this spike currently/",
                self._bc_prefix,
            )

    def _chargeSpike(self, jump: bool, v_from: bool, v_to: bool):
        """
        Callback for when a charge spike was detected.

        The spike threshold is set by `C_SPIKE_TH` and this is either for a
        jump or drop.

        Args:
            jump: Will be True if this was a jump, False if it was a drop.
            v_from: The value from which the jump occurred
            v_to: The value to which the jump occurred.
        """
        logging.info(
            "%s: Charge spike detected: %s (%s -> %s)",
            self._bc_prefix,
            "jump" if jump else "drop",
            v_from,
            v_to,
        )
        # Did we reach the end of charge?
        if self._v_mon.voltage > C_VOLTAGE_TH:
            if not self.transition(self.E_ch_done):
                logging.error(
                    "%s: Unable to transition to fully charged.",
                    self._bc_prefix,
                )
            else:
                # Transition to fully charged was successful, so we return.
                # If it was not successful, we will try to make it go to
                # ch_jump then.
                return

        # Update the state if possible
        if not self.transition(self.E_ch_jump if jump else self.E_ch_drop):
            logging.error(
                "%s: State transition not valid for this spike currently",
                self._bc_prefix,
            )

    def _dischargeSpike(self, jump: bool, v_from: float, v_to: float):
        """
        Callback for when a discharge spike was detected.

        The spike threshold is set by `D_SPIKE_TH` and this is either for a
        jump or drop.

        This callback will also be called when the discharge is completed. This
        happens when the battery voltage falls below the DW01_ Battery
        Protection chip **Overcharge Protection Voltage** on the TP4056_ board,
        which is typically around 2.4V.

        When the battery voltage reaches this threshold, the DW01_ switches the
        charge control MOSFET off. This looks like the battery was removed, and
        a voltage spike will have been triggered, but our state machine ignores
        voltage drops while discharging, and only cares about current spikes.

        The switching of the MOSFET also causes the discharge current to spike.
        Since at around 2.5v with a `LOAD_R` of 5Ω, the discharge current is
        still over 400mA which should be above our `D_SPIKE_TH` value.
        See the **Important** note for the `D_SPIKE_TH` config value.

        Args:
            jump: Will be True if this was a jump, False if it was a drop.
            v_from: The value from which the jump occurred
            v_to: The value to which the jump occurred.

        .. _DW01: https://www.best-microcontroller-projects.com/support-files/dw01a.pdf
        .. _TP4056: https://components101.com/modules/tp4056a-li-ion-battery-chargingdischarging-module
        """
        logging.info(
            "%s: Discharge spike detected: %s (%s -> %s, bat_v: %s)",
            self._bc_prefix,
            "jump" if jump else "drop",
            v_from,
            v_to,
            self._v_mon.voltage,
        )

        # Update the state if possible
        if not self.transition(self.E_dch_jump if jump else self.E_dch_drop):
            logging.error(
                "%s: State transition not valid for this spike currently/",
                self._bc_prefix,
            )

    def _resetMonitors(self):
        """
        Resets all monitors to their defaults.
        """
        for mon in (self._v_mon, self._ch_mon, self._dch_mon):
            mon.reset()

    def setID(self, bat_id: str | None = None) -> bool:
        """
        Sets the battery ID.

        This can only be done when in the `BCStateMachine.S_GET_ID` state.

        We set a default unique auto generated ID as soon as we go into the
        `BCStateMachine.S_GET_ID` state (see `BCStateMachine.transition()`). To
        accept this ID, pass the ``bat_id`` arg as None, else supply a max 10
        character string as ID.

        On success it will also transition to the next state.

        Args:
            bat_id: None to accept the current ID, or else a max 10 character
                string as the new ID.

        Returns:
            True if the new ID was set and the transition to the next state was
            successful, False with an error logged otherwise.
        """
        if not (bat_id is None or isinstance(bat_id, str)):
            logging.error("%s: Invalid bat ID to setID(): %s", self._bc_prefix, bat_id)
            return False

        if bat_id is not None and len(bat_id) > 10:
            logging.error(
                "%s: Bat ID can not be longer than 10 characters to setID(): %s",
                self._bc_prefix,
                bat_id,
            )
            return False

        if bat_id is not None:
            self._bat_id = bat_id

        return self.transition(self.E_set_id)

    def charge(self) -> bool:
        """
        Starts a charging cycle.

        This is done with an `BCStateMachine.E_charge` `BCStateMachine.transition()`.

        Returns:
            True if the transition was successful.
        """
        # Try the transition
        if self.transition(self.E_charge):
            return True

        logging.error("%s: Unable to start charging.", self._bc_prefix)
        return False

    async def _dischargeMonitor(self):
        """
        This coro is started for a discharge cycle, and monitors the battery
        voltage to detect when discharge is complete.

        Discharge is complete when the battery voltage (preferably using a
        windowing average for transient filtering) reaches the `D_VOLTAGE_TH`.

        The test for complete will be done every 100ms (hardcoded for now).

        Once discharge is complete, this coro will generate a
        `BCStateMachine.E_dch_done` event and exit.
        """
        logging.info("%s: Starting discharge monitor.", self._bc_prefix)

        # When we get here it may be right after a monitor reset which means
        # the voltage will not be correct. For this reason we pause here for a
        # bit to get the voltage monitor to register the correct voltage
        await asyncio.sleep_ms(1000)

        # Monitor for discharge complete
        while self._v_mon.voltage >= D_VOLTAGE_TH:
            await asyncio.sleep_ms(100)

        # Our voltage should slowly decrease, but we could be trigger if the
        # battery is yanked and the voltage spike detector did not pick the
        # spike up yet.
        # So, now we monitor the state for the V_SPIKE_TH_T period and if we
        # see the state change to Yanked, then we know it was the battery
        # being removed and not due to we reaching the end of change.
        start = time.ticks_ms()
        while (
            self.state != self.S_YANKED
            and time.ticks_diff(time.ticks_ms(), start) < V_SPIKE_TH_T
        ):
            await asyncio.sleep_ms(100)

        # We just exit on a yank
        if self.state == self.S_YANKED:
            logging.info(
                "%s: Exiting discharge monitor on battery being yanked.",
                self._bc_prefix,
            )
            return

        logging.info(
            "%s: Discharge complete with battery voltage at: %s. "
            "Exiting discharge monitor.",
            self._bc_prefix,
            self._v_mon.voltage,
        )

        if not self.transition(self.E_dch_done):
            logging.error(
                "%s: Unable to transition to fully discharged. "
                "Forcing Discharge off.",
                self._bc_prefix,
            )
            # Try to force switch discharging off
            self._cdControl(state=False, dch=True)

    def discharge(self) -> bool:
        """
        Starts a discharging cycle.

        This is done with an `BCStateMachine.E_discharge` `BCStateMachine.transition()`.

        Returns:
            True if the transition was successful.
        """
        # Try the transition
        if self.transition(self.E_discharge):
            return True

        logging.error("%s: Unable to start discharging.", self._bc_prefix)
        return False

    def pause(self):
        """
        Pauses the current charge or discharge cycle.

        This is done with an `BCStateMachine.E_pause` `BCStateMachine.transition()`.

        See:
            `resume()`

        Return:
            True if successful, False otherwise
        """
        # Attempt the transition
        if self.transition(self.E_pause):
            return True

        logging.error("%s: Unable to pause at the moment.", self._bc_prefix)
        return False

    def resume(self):
        """
        Resumes the current charge or discharge cycle.

        This is done with an `BCStateMachine.E_resume` `BCStateMachine.transition()`.

        See:
            `pause()`

        Return:
            True if successful, False otherwise
        """
        # Attempt the transition
        if self.transition(self.E_resume):
            return True

        logging.error("%s: Unable to resume at the moment.", self._bc_prefix)
        return False

    def resetMetrics(self) -> bool:
        """
        Resets the metrics for the current battery.

        This is done with an `BCStateMachine.E_reset_metrics`
        `BCStateMachine.transition()` from a paused state.

        Returns:
            True on success, False otherwise.
        """
        # Try the transition
        if self.transition(self.E_reset_metrics):
            return True

        logging.error("%s: Unable to reset metrics at the moment.", self._bc_prefix)
        return False

    def socMeasureToggle(self):
        """
        Starts a new SoC measure if not started already, or stops it if
        currently running.

        TODO:
            Need better docs here, or a link to where this is better
            documented.

        Returns:
            True on success, False on error with an error logged.
        """
        logging.info("%s: SoC measure toggle request. SoC: %s", self, self.soc_m)

        # Starting or cancelling the SoC Measure depends on the state of the
        # SoC FSM
        if self.soc_m.state == self.soc_m.ST_READY:
            # The SoC measurer is in the ready state, so we are good for
            # starting a SoC measure. But this can only be done if the BC is in
            # the S_BAT_ID state
            if self.state == self.S_BAT_ID:
                if self.soc_m.start():
                    logging.info("%s: SoC measure started.", self)
                    return True

                logging.error(
                    "%s: Error starting SoC measure.",
                    self,
                )
            else:
                logging.error(
                    "%s: SoC FSM is ready to measure SoC but we are not in the "
                    "correct state for that.",
                    self,
                )
            return False

        # The Soc FSM is not in the ready state, so we should be able to cancel it.
        if self.soc_m.cancel():
            logging.info("%s: Cancelled current Soc measurement process.", self)
            return True

        logging.error("%s: Error cancelling current SoC measurement process.", self)

        return False

    def reset(self) -> bool:
        """
        Resets the state after a battery was removed.

        This is done with an `BCStateMachine.E_reset_metrics`
        `BCStateMachine.transition()` from a paused state.

        Returns:
            True on success, False otherwise.
        """
        if self.transition(self.E_reset):
            return True

        logging.error("%s: Unable to reset the state currently.", self._bc_prefix)
        return False
