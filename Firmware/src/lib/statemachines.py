"""
Defines the required `Finite State Machines`_ used for the battery SoC_
tester. 

Attributes:

    telemetry_trigger: Very simple trigger mechanism to let the
        `telemetry.broadcast` task know it should immediately emit telemetry for
        a given `BatteryController`.

        The `telemetry` module will import this list and the
        `telemetry.broadcast` method will monitor it. If the
        `SoCStateMachine.monitorBCState` task needs to have the telemetry data
        for a given BC be emitted on completion of any of the SoC cycles, it
        will add the BC instance to this list, and then monitor the list
        waiting for the BC instance to not be there anymore.

        On the other side, `telemetry.broadcast` will also monitor this list.
        As soon as it sees any BC instances in the list, it will immediately
        emit the current state as telemetry data for that BC, and remove the BC
        from the list.

.. _`Finite State Machines`: https://en.wikipedia.org/wiki/Finite-state_machine
.. _SoC: https://www.batterydesign.net/battery-management-system/state-of-charge
"""

from micropython import const
import utime as time
import uasyncio as asyncio
from lib import ulogging as logging
from lib.uuid import shortUID

from config import (
    SOC_REST_TIME,
    SOC_NUM_CYCLES,
    D_V_RECOVER_TH,
    D_RECOVER_MAX_TM,
    D_RECOVER_MIN_TM,
)


# This is a very simple signaling method to let the Telemetry task know it
# needs to emit the telemetry for a specific BC.
telemetry_trigger = []


class BCStateMachine:
    """
    `Finite State Machine`_ to manage Battery Controller (`BatteryController`)
    states and transitions.

    State Diagram:

    .. image:: img/BC_StateDiagram.drawio.png
       :width: 100%

    See:
        [../../doc/Firmware/FSM_Design/BC_StateMachine.md] for MermaidJS_ source
        for this FSM

    Attributes:

        name: A name for the controller set on `__init__`

        S_DISABLED: Status: Battery controller disabled due to missing ADCs
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

        STATE_NAME: Human readable names for each of the above states.

            Used by the `state_name` method to return the string name for a
            given state.


        E_disable: Event: Disables this controller and FSM.
        E_init: Event: Initializes the FSM.
        E_v_jump: Event: A `BatteryController._voltageSpike` with rising voltage was detected.
        E_v_drop: Event: A `BatteryController._voltageSpike` with falling voltage was detected.
        E_ch_jump: Event: A `BatteryController._chargeSpike` with rising current was detected.
        E_ch_drop: Event: A `BatteryController._chargeSpike` with falling current was detected.
        E_dch_jump: Event: A `BatteryController._dischargeSpike` with rising current was detected.
        E_dch_drop: Event: A `BatteryController._dischargeSpike` with falling current was detected.
        E_ch_done: Event: Charging is done.

            When a `BatteryController._chargeSpike` is detected and the
            `BatteryController._v_mon` voltage is greater than `C_VOLTAGE_TH`

        E_dch_done: Event: Discharging is done.

            When the battery voltage monitored by `BatteryController._v_mon` is
            less than or equal to `D_VOLTAGE_TH`

        E_charge: Event: Start charging. Called to switch on MOSFET on success
        E_discharge: Event: Start discharging. Called to switch on MOSFET on success
        E_pause: Event: Pause Charge or Discharge. Called to switch MOSFET on success
        E_resume: Event: Resume Charge or Discharge. Called to switch MOSFET on success
        E_reset: Event: Resets monitor after yank
        E_get_id: Event: Event to indicate weare getting user input for the ID
        E_set_id: Event: ID input complete and battery ID has been set.
        E_reset_metrics: Event: Resets the metrics for a battery after halting charge/dischare

        EVENT_NAME: A dictionary of event constants above as keys, and their
            equivalent human readable event names as values.

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

            See:
                `STATE_NAME` for a list of the states.

    .. _`Finite State Machine`: https://en.wikipedia.org/wiki/Finite-state_machine
    .. _MermaidJS: https://mermaid.js.org/
    """

    # Possible states - excluding the unknown state with value of None
    # See Attributes docs in docstring
    S_DISABLED = const(0)
    S_NOBAT = const(1)
    S_BAT_NOID = const(2)
    S_GET_ID = const(3)
    S_BAT_ID = const(4)
    S_CHARGE = const(5)
    S_DISCHARGE = const(6)
    S_CHARGE_PAUSE = const(7)
    S_DISCHARGE_PAUSE = const(8)
    S_CHARGED = const(9)
    S_DISCHARGED = const(10)
    S_YANKED = const(11)

    # State names that should be in the same order as the state definitions
    # above. The state name is used as index into this list.
    # NOTE: This excludes the unknown (None) state because I like to complicate
    #       shit!
    STATE_NAME: list = [
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

    # Possible events. See Attributes in docstring for documentation.
    E_disable = const(100)
    E_init = const(101)
    E_v_jump = const(102)
    E_v_drop = const(103)
    E_ch_jump = const(104)
    E_ch_drop = const(105)
    E_dch_jump = const(106)
    E_dch_drop = const(107)
    E_ch_done = const(108)
    E_dch_done = const(109)
    E_charge = const(110)
    E_discharge = const(111)
    E_pause = const(112)
    E_resume = const(113)
    E_reset = const(114)
    E_get_id = const(115)
    E_set_id = const(116)
    E_reset_metrics = const(117)

    # Event ID names. See Attributes in docstring for documentation
    EVENT_NAME: dict = {
        E_disable: "E_disable",
        E_init: "E_init",
        E_v_jump: "E_v_jump",
        E_v_drop: "E_v_drop",
        E_ch_jump: "E_ch_jump",
        E_ch_drop: "E_ch_drop",
        E_dch_jump: "E_dch_jump",
        E_dch_drop: "E_dch_drop",
        E_ch_done: "E_ch_done",
        E_dch_done: "E_dch_done",
        E_charge: "E_charge",
        E_discharge: "E_discharge",
        E_pause: "E_pause",
        E_resume: "E_resume",
        E_reset: "E_reset",
        E_get_id: "E_get_id",
        E_set_id: "E_set_id",
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
            name: The battery controller name passes in to `__init__` as the
            ``name`` arg.

        TODO:
             Complete docs
        """
        self.name: str = name
        # We start off in the unknown state, and need to be initialized or
        # disabled ASAP.
        self.state: int | None = None

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


class SoCStateMachine:
    """
    `Finite State Machine`_ to manage measuring the SoC_ for a given
    `BatteryController`.

    State of Charge (SoC_) is measured as follows:

    * Fully charge the battery.
    * Fully discharge the battery, recording the total charge required.
    * Rest for a few minutes to normalise the battery and discharge load
      temperatures. Currently these temperatures are not measured, but could be
      done in a future version.
    * Fully charge the battery again, recording the total charge required.
    * Rest for a few minutes to normalise the battery temperature
    * Repeat the discharge/charge cycles for a user definable number of times.
    * Average the charge and discharge values, and record this as the battery
      SoC.

    State Diagram:

    .. image:: img/SoC_StateDiagram.drawio.png
       :width: 100%

    See:
        [../../doc/design/SoC_StateMachine.md] for MermaidJS_ source for this
        FSM

    Attributes:

        ST_READY: Status: Ready to start SoC measurement
        ST_CHARGE_1ST: Status: Busy with the initial charge cycle
        ST_CHARGE: Status: Busy charging - this is the general cycle charge
        ST_REST_CH: Status: Resting after charge - let temperatures settle
        ST_DISCHARGE: Status: Busy discharging - this is the general cycle discharge
        ST_REST_DCH: Status: Resting after discharge - let temperatures settle
        ST_COMPLETE: Status: SoC measure completed all cycles
        ST_CANCEL: Status: SoC measure cancel before it completed
        ST_ERROR: Status: The underlying `BatteryController` statues changed to
            an unexpected state.

            This may be due to the battery being removed while measuring SoC,
            or some other error or other event.

        STATE_NAME: Human readable names for each of the above states.

            Used by the `state_name` method to return the string name for a
            given state.

        EV_charge: Event: Charge event sent to underlying `BatteryController`
        EV_charge_complete: Event: Underlying `BatteryController` transitioned
            to the `BCStateMachine.S_CHARGED` state. Battery is charged.
        EV_discharge: Event: Discharge event sent to underlying `BatteryController`
        EV_discharge_complete: Event: Underlying `BatteryController` transitioned
            to the `BCStateMachine.S_DISCHARGED` state. Battery is discharged.
        EV_cycle_complete: Event: All SoC measurement `cycles` have been completed.
        EV_cancel: Event: A user cancel event received.
        EV_unexp_bc_state: Event: The underlying `BatteryController`
            transitioned to an unexpected state for the SoC Measurement state
            we are currently in.

        EVENT_NAME: A dictionary of event constants above as keys, and their
            equivalent human readable event names as values.

        TRANSITIONS: Describes the allowed transitions.

            Each key is a status (``ST_???``) describing the *from* state for a
            transition.

            The value is another dictionary where the key(s) is/are an event
            definition (``EV_???``) and the value is a destination *state*
            (``ST_???``) this even should change the `state` to.

            This dictionary defines all possible states and transitions as is
            described in the state diagram above.

        VALID_BC_STATES: A mapping of the states we expect the underlying BC
            (via `BCStateMachine`) to be for each of the states we are in.

            If the BC is not in one of the states we map here for our `state`,
            then there is an error and we will go to the `ST_ERROR` state.

            Note:
                For our `ST_COMPLETE`, `ST_CANCEL` and `ST_ERROR` states, we do
                not care about the BC state since in these states we would be
                done with SoC measure anyway.

        uid: A unique ID to identify this SoC Measurement.

            This is usefull to group event records together later. It will be
            an 8 character lowercase hex string like: ``5044d5c4``

        state: This will be the current state as defined by the various
            ``ST_???`` constants.

            See:
                `STATE_NAME` for a list of the states.

        cycles: The number or SoC measure cycles that must been completed. This
            is set from `__init__` on instance instantiation.

        cycle: The current SoC measure cycle we are on.

        cycle_tm: The current cycle duration thus far in seconds.

        in_progress: Can be used by external functions to determine if a SoC
            measure is currently in progress.

            The state of this attribute is managed in `monitorBCState`.

    .. _`Finite State Machine`: https://en.wikipedia.org/wiki/Finite-state_machine
    .. _SoC: https://www.batterydesign.net/battery-management-system/state-of-charge
    .. _MermaidJS: https://mermaid.js.org/
    """

    # Possible states
    ST_READY = const(0)
    ST_CHARGE_1ST = const(1)
    ST_CHARGE = 2
    ST_REST_CH = const(3)
    ST_DISCHARGE = const(4)
    ST_REST_DCH = const(5)
    ST_COMPLETE = const(6)
    ST_CANCEL = const(7)
    ST_ERROR = const(8)

    # State names that should be in the same order as the state definitions
    # above. The state name is used as index into this list.
    STATE_NAME: list = [
        "Ready",  # ST_READY
        "Initial Charge",  # ST_CHARGE_1ST
        "Charging",  # ST_CHARGE
        "Resting",  # ST_REST_CH
        "Discharging",  # ST_DISCHARGE
        "Resting",  # ST_REST_DCH
        "Completed",  # ST_COMPLETE
        "Canceled",  # ST_CANCEL
        "Error",  # ST_ERROR
    ]

    # Possible events. See Attributes in docstring for documentation.
    EV_charge = const(100)
    EV_charge_complete = const(101)
    EV_discharge = const(102)
    EV_discharge_complete = const(103)
    EV_cycle_complete = const(104)
    EV_cancel = const(105)
    EV_unexp_bc_state = const(106)

    # Event ID names. See Attributes in docstring for documentation
    EVENT_NAME: dict = {
        EV_charge: "EV_charge",
        EV_charge_complete: "EV_charge_complete",
        EV_discharge: "EV_discharge",
        EV_discharge_complete: "EV_discharge_complete",
        EV_cycle_complete: "EV_cycle_complete",
        EV_cancel: "EV_cancel",
        EV_unexp_bc_state: "EV_unexp_bc_state",
    }

    # Valid transition definitions
    TRANSITIONS: dict = {
        ST_READY: {  # From ready state
            EV_charge: ST_CHARGE_1ST,
            EV_unexp_bc_state: ST_ERROR,
        },
        ST_CHARGE_1ST: {  # From initial charge state
            EV_charge_complete: ST_REST_CH,
            EV_cancel: ST_CANCEL,
            EV_unexp_bc_state: ST_ERROR,
        },
        ST_REST_CH: {  # From resting after a charge cycle
            EV_discharge: ST_DISCHARGE,
            EV_cancel: ST_CANCEL,
            EV_unexp_bc_state: ST_ERROR,
        },
        ST_DISCHARGE: {  # From the discharging state
            EV_discharge_complete: ST_REST_DCH,
            EV_cancel: ST_CANCEL,
            EV_unexp_bc_state: ST_ERROR,
        },
        ST_REST_DCH: {  # From resting after a discharge cycle
            EV_charge: ST_CHARGE,
            EV_cancel: ST_CANCEL,
            EV_unexp_bc_state: ST_ERROR,
        },
        ST_CHARGE: {  # From a charge state
            EV_charge_complete: ST_REST_CH,  # Only if we have cycles left
            EV_cycle_complete: ST_COMPLETE,  # After all SoC test cycles
            EV_cancel: ST_CANCEL,
            EV_unexp_bc_state: ST_ERROR,
        },
        ST_ERROR: {
            # Can not go anywhere from Error state, must exit and reset
        },
        ST_COMPLETE: {
            # Can not go anywhere from Completed state, must exit and reset
        },
        ST_CANCEL: {
            # Can not go anywhere from Cancelled state, must exit and reset
        },
    }

    # A mapping of the states we expect the underlying BC (via BCStateMachine)
    # to be for each of the states we are in. If the BC is not in one of the
    # states we map here for our state, then there is an error monitorBCState
    # will transition us to the error state.
    VALID_BC_STATES = {
        # In our ready state, the BC must be in S_BAT_ID state
        ST_READY: [BCStateMachine.S_BAT_ID],
        # The initial charging stage. The BC can be busy charging, completed
        # charging.
        ST_CHARGE_1ST: [
            BCStateMachine.S_CHARGE,
            BCStateMachine.S_CHARGED,
        ],
        # Same as for 1st charge stage
        ST_CHARGE: [
            BCStateMachine.S_CHARGE,
            BCStateMachine.S_CHARGED,
        ],
        # While in the discharging cycle, the BC must be discharging or
        # discharged.
        ST_DISCHARGE: [
            BCStateMachine.S_DISCHARGE,
            BCStateMachine.S_DISCHARGED,
        ],
        # While resting we could be in the charged or discharged state
        ST_REST_CH: [
            BCStateMachine.S_CHARGED,
            BCStateMachine.S_DISCHARGED,
        ],
        ST_REST_DCH: [
            BCStateMachine.S_CHARGED,
            BCStateMachine.S_DISCHARGED,
        ],
        # When charging is complete, the BC should be in reset state
        ST_COMPLETE: [BCStateMachine.S_BAT_ID],
        # Could be any state
        ST_CANCEL: None,
        # This could be in any state...
        ST_ERROR: None,
    }

    def __init__(self, bc: "BatteryController", cycles: int = SOC_NUM_CYCLES):
        """
        Constructor.

        Args:
            bc: The `BatteryController` instance we are doing SoC measurements
                for
            cycles: The number of SoC Measurement cycles to run.
        """
        self._bc = bc
        # Set the initial state and total cycles.
        self.state = self.ST_READY
        # This number of cycles we need to complete
        self.cycles = cycles
        # This will be cycle counter.
        self.cycle = 0
        # This will be the number of seconds the current cycle operation has
        # been going for while doing a SoC measurement.
        self.cycle_tm = 0
        # Can be tested to determine if a SoC measurement is in progress
        self.in_progress = False
        # UID to identify each full SoC from. Will be set and cleared by monitorBCState
        self.uid = None

    def __str__(self) -> str:
        """
        String representation of the instance and current state.

        Returns:
            The FSM name.
        """
        return f"SoC FSM ({self.state_name})"

    @property
    def state_name(self) -> str:
        """
        Returns the current state as a string.
        """
        return self.STATE_NAME[self.state]

    def _resetBC(self):
        """
        Called to reset the BC to the S_BAT_ID state.

        This is called before we start a charge or discharge, or when an error
        condition was detected or when cancelling the SoC measurement.

        We will check if the BC is currently in the charging or discharging
        state and then issue a pause event.

        If the BC is paused, charged or discharged, we will then issue a
        metrics reset event.

        Any other BC state will be ignored and an error logged.

        Returns:
            True on success False with error logged on error
        """
        # We need to first move the BC to the paused state before we can do a
        # metrics reset if it is dis/charging
        if self._bc.state in (self._bc.S_CHARGE, self._bc.S_DISCHARGE):
            # We expect it to work, so no error checking here
            self._bc.transition(self._bc.E_pause)

        # We can reset_metrics for the dis/charged or paused states
        if self._bc.state in (
            self._bc.S_CHARGE_PAUSE,
            self._bc.S_DISCHARGE_PAUSE,
            self._bc.S_CHARGED,
            self._bc.S_DISCHARGED,
        ):
            # Then we can reset
            return self._bc.transition(self._bc.E_reset_metrics)

        logging.error(
            "%s: BC in unexpected state while trying to reset to S_BAT_ID state : %s",
            self,
            self._bc.state_name,
        )

        return False

    def transition(self, event):
        """
        Call to transition to the next state.

        Args:
            event: Any of the ``EV_???`` event constants defined for this class.

        Side Effect:
            On success `state` will be updated to the correct state based on
            the current state and event.

        Returns:
            True if the transition was successful, False otherwise, with any
            failures error logged.
        """
        logging.info(
            "%s: Transition request for event %s", self, self.EVENT_NAME[event]
        )

        # An EV_charge_complete event may be changed to an EV_cycle_complete
        # event if the battery is fully charged and we have reached the max
        # cycle count.
        if event == self.EV_charge_complete and self.cycle == self.cycles:
            event = self.EV_cycle_complete
            logging.info(
                "%s: Transition event %s changed to %s due SoC cycles completed.",
                self,
                self.EVENT_NAME[self.EV_charge_complete],
                self.EVENT_NAME[self.EV_cycle_complete],
            )

        # Check for valid transition
        if event not in self.TRANSITIONS[self.state]:
            logging.error(
                "%s: Invalid event %s from state %s",
                self,
                self.EVENT_NAME.get(event, event),
                self.state_name,
            )
            return False

        # Make the transition
        self.state = self.TRANSITIONS[self.state][event]
        logging.info(
            "%s: Transitioned to state: %s (%s)",
            self,
            self.state_name,
            self.state,
        )

        # Handle some house keeping depending on the state we end up in.
        if self.state == self.ST_REST_CH:
            # Every time we rest after a full charge cycle, we increment the
            # cycle counter.
            self.cycle += 1

        # For safety, if we go to the error state, make sure the BC is not
        # still charging or discharging
        if self.state == self.ST_ERROR and self._bc.state in (
            self._bc.S_CHARGE,
            self._bc.S_DISCHARGE,
        ):
            self._resetBC()

        # Perform BC functions depending on the event

        # If this is a charge event, we need to start charging on the BC after a
        # reset if needed
        if event == self.EV_charge:
            # We do not need to reset the BC for the ST_CHARGE_1ST state since
            # it would already be reset and ready
            if self.state != self.ST_CHARGE_1ST:
                self._resetBC()
            # Start charging
            return self._bc.transition(self._bc.E_charge)

        # If this is a discharge event, we need to start discharging on the BC
        # after resetting the BC
        if event == self.EV_discharge:
            self._resetBC()
            return self._bc.transition(self._bc.E_discharge)

        # On a cancel event, we need to get the BC to the reset state if not
        # there already.
        if event == self.EV_cancel and self._bc.state != self._bc.S_BAT_ID:
            self._resetBC()

        return True

    async def monitorBCState(self):
        """
        Coro to monitor the underlying `_bc` state, and issues transitions on
        state changes.

        We are started immediately on instantiation from `__init__` and will
        keep running until one of the final states have been reached, after
        which we exit.

        The final states are any of ST_COMPLETE, ST_CANCEL or ST_ERROR.

        Before exit, we will delay a short period to give the telemetry monitor
        time to report the state if needed, and then reset the state to
        ST_READY.

        The `in_progress` attribute will also be set while this coro is
        running, and be reset before it exits.
        """
        # The loop delay in ms
        delay = 200

        # Will be used as cycle timer
        cycle_start = time.ticks_ms()

        # We keep track of cycle times in seconds, but we only use ticks_ms as
        # the highest resolution of ticks. This means that we either need to
        # divide ms ticks by 1000 for all operations, or we need to multiply
        # the config values by 1000.
        # Since division is normally orders of magnitude slower than
        # multiplication, we convert our config times here to ms one, and from
        # then on all timers use ms.
        rest_time = SOC_REST_TIME * 1000

        # Get a SoC measure uid
        self.uid = shortUID()

        logging.info("%s: Starting BC State monitor for BC: %s", self, self._bc)

        # While we are not in a done state, we loop
        while self.state not in (self.ST_COMPLETE, self.ST_CANCEL, self.ST_ERROR):
            # Delay a bit
            await asyncio.sleep_ms(delay)

            # Update the cycle time
            self.cycle_tm = time.ticks_diff(time.ticks_ms(), cycle_start) // 1000

            # First thing we do on every loop is to check if we have not
            # changed to some unexpected state. If so, we transition with an
            # EV_unexp_bc_state event
            if (
                self.VALID_BC_STATES[self.state] is not None
                and self._bc.state not in self.VALID_BC_STATES[self.state]
            ):
                err = (
                    f"{self}: BC [{self._bc.name}] is in unexpected state "
                    + f"'{self._bc.state_name}' for our '{self.state_name}' state. "
                    + "Transitioning to error state."
                )
                logging.error(err)
                self.transition(self.EV_unexp_bc_state)
                continue

            # When we start up we will be in the ready state. We auto
            # transition to start charging from this state.
            if self.state == self.ST_READY:
                # We have to set the in_progress flag as early as possible.
                # Technically we can set it as soon as the coro starts, but
                # let's be more pedantic and do it when we are actually
                # starting the SoC measure, OK?
                self.in_progress = True
                # And start....
                self.transition(self.EV_charge)
                cycle_start = time.ticks_ms()
                continue

            # Has the BC completed charging and we have not transitioned to
            # resting yet??
            if self._bc.state == self._bc.S_CHARGED and self.state != self.ST_REST_CH:
                # We now transition with a charge completed event
                # NOTE: This event may be changed to an EV_cycle_complete event
                # if the transition() method sees that we have completed all
                # cycles.
                self.transition(self.EV_charge_complete)
                cycle_start = time.ticks_ms()
                continue

            # Has the BC completed discharging but we have not transitioned to
            # the rest state yet?
            if (
                self._bc.state == self._bc.S_DISCHARGED
                and self.state != self.ST_REST_DCH
            ):
                # We now transition with a discharge completed event and reset
                # the cycle timer
                self.transition(self.EV_discharge_complete)
                cycle_start = time.ticks_ms()
                continue

            # Are we resting after a discharge?
            if self.state == self.ST_REST_DCH:
                # We can only come out of rest if:
                # * The battery voltage has recover to at least D_V_RECOVER_TH
                # * The battery temperature has dropped to D_RECOVER_TEMP
                # ...but...
                # We have no temperature monitor at the moment, so we force a
                # min rest period which should be greater than D_RECOVER_MAX_TM
                if (
                    # pylint: disable=protected-access
                    self._bc._v_mon.voltage >= D_V_RECOVER_TH
                    and self.cycle_tm >= D_RECOVER_MIN_TM
                ):
                    # We're done resting. Start another charging cycle
                    self.transition(self.EV_charge)
                    cycle_start = time.ticks_ms()
                    continue

                if self.cycle_tm >= D_RECOVER_MAX_TM:
                    logging.error(
                        "%s: Battery voltage did not recover after "
                        "discharge and additional resting. "
                        "Aborting SoC measure.",
                        self,
                    )
                    self.transition(self.EV_unexp_bc_state)
                    continue

            # Are we resting after a charge cycle?
            if self.state == self.ST_REST_CH:
                # Continue resting if we are not done yet. The cycle timer
                # would have been set when we started this cycle
                if time.ticks_diff(time.ticks_ms(), cycle_start) < rest_time:
                    continue

                # We're done resting. Go into a discharge cycle now
                self.transition(self.EV_discharge)
                cycle_start = time.ticks_ms()

            # TODO: This is where we can check for charging longer than it
            # should have.

        # We're done with the loop. Log and info message.
        logging.info("%s: SoC measure done. Exiting BC monitor.", self)

        # We want the telemetry broadcaster to immediately emit the telemetry
        # for this BC. We do this by signaling it through the telemetry_trigger
        # list.
        telemetry_trigger.append(self._bc)
        # We give the Telemetry emitter 20 * 100ms to emit the telemetry data
        for _ in range(20):
            # To waste as little time as possible, we check the trigger every
            # 100ms
            await asyncio.sleep_ms(100)

            # Has it been removed?
            # TODO: There is a possible race condition here, in that we may have
            #      added the BC, then the telemetry picked it up and emitted
            #      the data. Then while we sleep above, another coro adds the
            #      same BC to the telemetry_trigger trigger again.
            #      In this case we will find it in there, and stay in the loop
            #      for the wrong reason.
            #      Worse, if we exit this loop the check below could then
            #      remove that telemetry_trigger before it was emitted.
            #      Multitasking is difficult!!
            if self._bc not in telemetry_trigger:
                break

        # We remove the trigger and log an error if still there.
        if self._bc in telemetry_trigger:
            logging.error("%s: Telemetry was not emitted for this cycle.")
            telemetry_trigger.remove(self._bc)

        # Reset our state before we exit this coro
        self.state = self.ST_READY
        self.cycle = 0
        self.cycle_tm = 0
        self.in_progress = False
        self.uid = None

    def start(self):
        """
        Starts a SoC measurements if we are in the correct state.

        Returns:
            True on success, False on failure with an error message logged.
        """
        logging.info("%s: Request to start SoC measure....", self)

        # We can reset to the ready state after a previous completed, canceled
        # or error run
        if self.state in (self.ST_COMPLETE, self.ST_CANCEL, self.ST_ERROR):
            self.state = self.ST_READY

        # We can not start if we are not in the Ready state
        if self.state != self.ST_READY:
            logging.error("%s: Can not start SoC measure from this state.", self)
            return False

        # Start the monitor
        asyncio.create_task(self.monitorBCState())

        return True

    def cancel(self):
        """
        Call this to cancel the current SoC measurement.

        Returns:
            True on success, False on error
        """
        return self.transition(self.EV_cancel)
