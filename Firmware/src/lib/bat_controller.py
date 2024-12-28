"""
Battery Controller and State Machine module.

-------------------- from old charge_controller.py

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

from micropython import const
import uasyncio as asyncio
from lib import ulogging as logging
from lib.adc_monitor import VoltageMonitor, ChargeMonitor
from lib.utils import genBatteryID, ewAverage

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


class StateMachine:
    """
    `Finite State Machine`_ to manage Battery Controller (`BatteryController`)
    states and transitions.

    State Diagram:

    .. image:: ../../doc/design/BC_StateMachine.drawio.png

    See:
        [../../doc/design/BC_StateMachine.md] for MermaidJS_ source for this
        FSM

    Attributes:
        S_NOBAT: Status: No Battery
        S_BAT_NOID: Status: Battery, No ID
        S_GET_ID: Status: Input Bat ID
        S_BAT_ID: Status: Battery + ID
        S_CHARGE: Status: Charging
        S_DISCHARGE: Status: Discharging
        S_CHARGE_PAUSE: Status: Charging Paused
        S_DISCHARGE_PAUSE: Status: Disharging Paused
        S_CHARGED: Status: Charge completed
        S_DISCHARGED: Status: Disharge Completed
        S_YANKED: Status: Battery removed

        E_v_jump: Event: > +2V change in battery voltage in 300ms
        E_v_drop: Event: > -2V change in battery voltage in 500ms (this rate is slower)
        E_ch_jump: Event: > +200mA change in charge current in 100ms
        E_ch_drop: Event: > -200mA change in charge current in 100ms
        E_dch_jump: Event: > +200mA change in discharge current in 100ms
        E_dch_drop: Event: > -200mA change in discharge current in 100ms
        E_ch_done: Event: ?? Not sure how to know charge is completed yet
        E_dch_done: Event: ?? Not sure how to know discharge is completed yet
        E_ch_on: Event: Charge switched on
        E_ch_off: Event: Charge switched off
        E_dch_on: Event: Discharge switched on
        E_dch_off: Event: Discharge switched off
        E_reset: Event: Resets monitor after yank
        E_get_id: Event: Event to indicate weare getting user input for the ID
        E_set_id: Event: ID input complete and battery ID has been set.
        E_reset_metrics: Event: Resets the metrics for a battery after halting charge/dischare

        TRANSITIONS: Describes the allowed transitions.

            Each key is a status (``S_???``) describing the *from* state for a
            transition.

            The value is another dictionary where the key(s) is/are an event
            definition (``E_???``) and the value is a destination *state*
            (``ST_???``) this even should change the `state` to.

            This dictionary defines all possible states and transitions as is
            described in the state diagram above.

        state: This will be the current state as defined by the various
            ``S_???`` constants.

    .. _`Finite State Machine`: https://en.wikipedia.org/wiki/Finite-state_machine
    .. _MermaidJS: https://mermaid.js.org/
    """

    # Possible states - excluding the unknown state with value of None
    S_DISABLED = const(0)  # Battery controller disabled due to missing ADCs
    S_NOBAT = const(1)  # No Battery
    S_BAT_NOID = const(2)  # Battery, No ID
    S_GET_ID = const(3)  # Input Bat ID
    S_BAT_ID = const(4)  # Battery + ID
    S_CHARGE = const(5)  # Charging
    S_DISCHARGE = const(6)  # Discharging
    S_CHARGE_PAUSE = const(7)  # Charging Paused
    S_DISCHARGE_PAUSE = const(8)  # Disharging Paused
    S_CHARGED = const(9)  # Charge completed
    S_DISCHARGED = const(10)  # Disharge Completed
    S_YANKED = const(11)  # Battery removed

    # State names that should be in the same order as the state definitions
    # above. The state name is used as index into this list.
    # NOTE: This excludes the unknown (None) state because I like to complicate
    #       shit!
    STATE_NAME = [
        "Disabled",  # S_DISABLED
        "No Battery",  # S_NOBAT
        "Battery, No ID",  # S_BAT_NOID
        "Awaiting Bat ID",  # S_GET_ID
        "Battery+ID",  # S_BAT_ID
        "Charging",  # S_CHARGE
        "Discharging",  # S_DISCHARGE
        "Charge Paused",  # S_CHARGE_PAUSE
        "Discharge Paused",  # S_DISCHARGE_PAUSE
        "Charged",  # S_CHARGED
        "Discharged",  # S_DISCHARGED
        "Yanked",  # S_YANKED
    ]

    # Possible events
    E_disable = const(100)  # FSM disabled
    E_init = const(101)  # FSM initialize event
    E_v_jump = const(102)  # > +2V change in battery voltage in 300ms
    # > -2V change in battery voltage in 500ms (this rate is slower)
    E_v_drop = const(103)
    E_ch_jump = const(104)  # > +200mA change in charge current in 100ms
    E_ch_drop = const(105)  # > -200mA change in charge current in 100ms
    E_dch_jump = const(106)  # > +200mA change in discharge current in 100ms
    E_dch_drop = const(107)  # > -200mA change in discharge current in 100ms
    E_ch_done = const(108)  # ?? Not sure how to know charge is completed yet
    E_dch_done = const(109)  # ?? Not sure how to know discharge is completed yet
    E_charge = const(110)  # Start charging. Caller to switch on MOSFET on success
    E_discharge = const(111)  # Start discharging. Caller to switch on MOSFET on success
    # Pause Charge or Discharge. Caller to switch MOSFET on success
    E_pause = const(112)
    # Resume Charge or Discharge. Caller to switch MOSFET on success
    E_resume = const(113)
    E_reset = const(114)  # Resets monitor after yank
    E_get_id = const(115)  # Event to indicate weather getting user input for the ID
    E_set_id = const(116)  # ID input complete and battery ID has been set.
    # Resets the metrics for a battery after halting charge/discharge
    E_reset_metrics = const(117)

    # Event ID names
    EVENT_NAME = {
        E_disable: "E_disable",  # FSM disabled
        E_init: "E_init",  # FSM initialize event
        E_v_jump: "E_v_jump",  # > +2V change in battery voltage in 300ms
        E_v_drop: "E_v_drop",  # > -2V change in battery voltage in 500ms (this rate is slower)
        E_ch_jump: "E_ch_jump",  # > +200mA change in charge current in 100ms
        E_ch_drop: "E_ch_drop",  # > -200mA change in charge current in 100ms
        E_dch_jump: "E_dch_jump",  # > +200mA change in discharge current in 100ms
        E_dch_drop: "E_dch_drop",  # > -200mA change in discharge current in 100ms
        E_ch_done: "E_ch_done",  # ?? Not sure how to know charge is completed yet
        E_dch_done: "E_dch_done",  # ?? Not sure how to know discharge is completed yet
        E_charge: "E_charge",  # Start charging. Caller to switch on MOSFET on success
        E_discharge: "E_discharge",  # Start discharging. Caller to switch on MOSFET on success
        E_pause: "E_pause",  # Pause Charge or Discharge. Caller to switch MOSFET on success
        E_resume: "E_resume",  # Resume Charge or Discharge. Caller to switch MOSFET on success
        E_reset: "E_reset",  # Resets monitor after yank
        E_get_id: "E_get_id",  # Event to indicate weather getting user input for the ID
        E_set_id: "E_set_id",  # ID input complete and battery ID has been set.
        # Resets the metrics for a battery after halting charge/discharge
        E_reset_metrics: "E_reset_metrics",
    }

    # Valid transition definitions
    TRANSITIONS: dict = {
        None: {  # From: initial state
            # To: Disabled state
            E_disable: S_DISABLED,
            # To: Initial state
            E_init: S_NOBAT,
        },
        S_DISABLED: {},  # No transitions available from disabled
        S_NOBAT: {  # From: no battery inserted
            # To: Battery inserted on battery voltage jump
            E_v_jump: S_BAT_NOID,
        },
        S_BAT_NOID: {  # From: Battery inserted, but waiting for an ID
            # To: Getting the battery ID on a get_id event
            E_get_id: S_GET_ID,
            # To: Battery removed on voltage drop
            E_v_drop: S_YANKED,
        },
        S_GET_ID: {  # From: Busy getting battery ID
            # To: Set ID from user input on set_id event
            E_set_id: S_BAT_ID,
            # To: Yank while getting the ID
            E_v_drop: S_YANKED,
        },
        S_BAT_ID: {  # From: Idle battery with ID
            # To: Start Charging on charge event
            E_charge: S_CHARGE,
            # To: Start Discharging on discharge event
            E_discharge: S_DISCHARGE,
            # To: Yanked on voltage drop
            E_v_drop: S_YANKED,
        },
        S_CHARGE: {  # From: Charging
            # To: Pausing the charge on pause event
            E_pause: S_CHARGE_PAUSE,
            # To: Yank on ch_drop event
            E_ch_drop: S_YANKED,
            # To: Charge complete on ch_done event
            E_ch_done: S_CHARGED,
        },
        S_CHARGE_PAUSE: {  # From: Charging paused
            # To: Continue charging on resume event
            E_resume: S_CHARGE,
            # To: Reset metrics on reset_metrics event
            E_reset_metrics: S_BAT_ID,
            # To: Yank on v_drop event
            E_v_drop: S_YANKED,
        },
        S_CHARGED: {  # From: Fully charged
            # To: Reset metrics on reset_metrics event
            E_reset_metrics: S_BAT_ID,
            # To: Yank on v_drop event
            E_v_drop: S_YANKED,
        },
        S_DISCHARGE: {  # From: Discharging
            # To: Pausing the discharge pause event
            E_pause: S_DISCHARGE_PAUSE,
            # To:  Yank
            E_dch_drop: S_YANKED,
            # To: Discharge complete on dch_done event
            E_dch_done: S_DISCHARGED,
        },
        S_DISCHARGE_PAUSE: {  # From: Charging
            # To: Continue discharging on resume event
            E_resume: S_DISCHARGE,
            # To: Reset metrics on reset_metrics event
            E_reset_metrics: S_BAT_ID,
            # To: Yank on v_drop event
            E_v_drop: S_YANKED,
        },
        S_DISCHARGED: {  # From: Fully discharged
            # To: Reset metrics on reset_metrics event
            E_reset_metrics: S_BAT_ID,
            # To: Yank on v_drop event
            E_v_drop: S_YANKED,
        },
        S_YANKED: {  # From: Battery removed
            # To: Reset after yank
            E_reset: S_NOBAT,
            # To: Auto reset when inserting a battery while in yanked state
            E_v_jump: S_BAT_NOID,
        },
    }

    def __init__(self, name: str):
        """
        Instance init.

        Args:
            name: A name for this FSM. Usually linked to the what???

        Attributes:
            _name: The battery controller name passes in to `__init__` as the
            ``name`` arg.

        TODO:
             Complete docs
        """
        self._name: str = name
        # We start off in the unknown state, and need to be initialized or
        # disabled ASAP.
        self.state: int | None = None

    def __str__(self) -> str:
        """
        String representation of the instance.

        Returns:
            The FSM name.
        """
        return self._name

    @property
    def state_name(self) -> str:
        """
        Returns the current state as a string.
        """
        return self.STATE_NAME[self.state]

    def transition(self, event: int) -> bool:
        """
        Call to transition to the next state.

        Args:
            event: Any of the ``E_???`` event constants defined for this class.

        Side Effect:
            On success `state` will be updated to the correct state based on
            the current state and event.

        Returns:
            True if the transition was successful, False otherwise, with an
            failure error logged.
        """
        # Check for valid transition
        if event in self.TRANSITIONS[self.state]:
            self.state = self.TRANSITIONS[self.state][event]
            logging.info(
                "%s (FSM): Transitioned to state: %s (%s)",
                self,
                self.state_name,
                self.state,
            )
            return True

        logging.error(
            "%s (FSM): Invalid event %s from state %s",
            self,
            self.EVENT_NAME.get(event, event),
            self.state_name,
        )
        return False


class BatteryController(StateMachine):
    """
    A Battery Controller based on the `StateMachine` for managing and
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

    Attributes:

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
        as scheduler starts running.

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
        self._bc_prefix = f"{self._name} (BC)"

        # The charge and discharge control pins
        self._pin_ch = Pin(ch_cfg[0], Pin.OUT, value=0)  # Charge control pin
        self._pin_dch = Pin(dch_cfg[0], Pin.OUT, value=0)  # Discharge control pin

        # This will be the ID given to the battery currently in the holder.
        self._bat_id: str = ""
        # This a counter that the _genID() method will increment every time it
        # auto generates a new ID
        self._bat_cnt = 1

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
            # Do not do anything further
            return

        # Not disabled, so we can transition to the initialized state.
        self.transition(self.E_init)

        # Tracks the last few battery voltage readings to help detect fully
        # charge/discharged states
        self._bat_v_track = 0

        # And start the battery voltage tracker
        asyncio.create_task(self._trackBatV())

    def transition(self, event: int) -> bool:
        """
        Overrides the `StateMachine.transition` method so we can apply certain
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
            # Nothing to fail here ,so we return True
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
            # NOTE: If our FSM is correct we should not ever get an error here.
            return self._cdControl(state=True, dch=True)

        # When we transitioned to discharging paused or completed, we need to
        # switch the controller off
        if self.state in (self.S_DISCHARGE_PAUSE, self.S_DISCHARGED):
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
                # WE are switching off, so we can continue on to the next.
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

    async def _trackBatV(self):
        """
        AsyncIO task that tracks an average of the battery voltage over a
        small sample window to help with fully charged and discharged
        detection.

        When fully discharged, the DW01 protection chips disconnects the
        battery which means that by the time the discharge callback is called,
        we do not know what the battery voltage was, especially since the
        voltage monitor is not guaranteed to use a filter to average the
        voltage.

        For this reason, we keep our own voltage average in `_bat_v_track`
        using this coro that updates the average every 1/2 second over a 3
        sample window.
        """
        self._bat_v_track = 0
        alpha = 1 / 3  # 3 sample window

        while True:
            await asyncio.sleep_ms(500)
            self._bat_v_track = ewAverage(alpha, self._v_mon.voltage, self._bat_v_track)

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
            "%s: Voltage spike detected: %s (%s -> %s)",
            self._bc_prefix,
            "jump" if jump else "drop",
            v_from,
            v_to,
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
        if self._bat_v_track > C_VOLTAGE_TH:
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
            "%s: Discharge spike detected: %s (%s -> %s, track_v: %s)",
            self._bc_prefix,
            "jump" if jump else "drop",
            v_from,
            v_to,
            self._bat_v_track,
        )
        # Did we reach the end of charge?
        if self._bat_v_track < D_VOLTAGE_TH:
            if not self.transition(self.E_dch_done):
                logging.error(
                    "%s: Unable to transition to fully discharged.",
                    self._bc_prefix,
                )
            else:
                # Transition to fully discharged was successful, so we return.
                # If it was not successful, we will try to make it go to
                # dch_jump then.
                return

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

        This can only be done when in the `S_GET_ID` state.

        We set a default unique auto generated ID as soon as we go into the
        `S_GET_ID` state (see `transition()`). To accept this ID, pass the
        ``bat_id`` arg as None, else supply a max 10 character string as ID.

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

        This is done with an `E_charge` `transition()`.

        Returns:
            True if the transition was successful.
        """
        # Try the transition
        if self.transition(self.E_charge):
            return True

        logging.error("%s: Unable to start charging.", self._bc_prefix)
        return False

    def discharge(self) -> bool:
        """
        Starts a discharging cycle.

        This is done with an `E_discharge` `transition()`.

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

        This is done with an `E_pause` `transition()`.

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

        This is done with an `E_resume` `transition()`.

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

        This is done with an `E_reset_metrics` `transition()` from a paused state.

        Returns:
            True on success, False otherwise.
        """
        # Try the transition
        if self.transition(self.E_reset_metrics):
            return True

        logging.error("%s: Unable to reset metrics at the moment.", self._bc_prefix)
        return False

    def reset(self) -> bool:
        """
        Resets the state after a battery was removed.

        This is done with an `E_reset_metrics` `transition()` from a paused state.

        Returns:
            True on success, False otherwise.
        """
        if self.transition(self.E_reset):
            return True

        logging.error("%s: Unable to reset the state currently.", self._bc_prefix)
        return False

    @property
    def bat_v(self) -> int:
        """
        Property to return the current battery voltage.

        Returns:
            The battery voltage in mV.
        """
        return self._v_mon.voltage

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
