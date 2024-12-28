Battery Controller State Machine
================================

Below is a [state diagram] that governs the [FSM] for controlling and monitoring
the Battery Controller.

```mermaid
---
title: Battery Control and Monitor
---

stateDiagram-v2
    direction TB

    classDef yanked fill:#a44,color:white,font-weight:bold,stroke-width:2px,stroke:#700
    classDef charged fill:#4a4,color:white,font-weight:bold,stroke-width:2px,stroke:#070
    classDef discharged fill:#d50,color:white,font-weight:bold,stroke-width:2px,stroke:#a20
    classDef paused fill:#660,color:white,font-weight:bold,stroke-width:2px,stroke:#880
    classDef currentflow fill:#036,color:white,font-weight:bold,stroke-width:2px,stroke:#059
    classDef ready fill:#336,color:white,font-weight:bold,stroke-width:2px,stroke:#559
    
    %% Possible states and actions to perform when
    %% Transitioning to that state.
    DISABLED: Disabled
    note right of DISABLED
        Monitors disabled
        Ch and Dch Off
    end note
    NOBAT: No Battery
    note right of NOBAT
        Ch and Dch Stop
        Reset Bat ID
    end note
    BAT_NOID: Battery, No ID
    note right of BAT_NOID
        Gen Bat ID
    end note
    GET_ID: Input Bat ID
    BAT_ID: Battery + ID
    note right of BAT_ID
        Reset monitors
    end note
    CHARGE: Charging
    note left of CHARGE
        Ch Start
    end note
    CHARGE_PAUSE: Charging Paused
    note left of CHARGE_PAUSE
        Ch Stop
    end note
    CHARGED: Charge completed
    note right of CHARGED
        Ch Stop
    end note
    DISCHARGE: Discharging
    note left of DISCHARGE
        Dch Sart
    end note
    DISCHARGE_PAUSE: Disharging Paused
    note left of DISCHARGE_PAUSE
        Dch Stop
    end note
    DISCHARGED: Disharge Completed
    note right of DISCHARGED
        Dch Stop
    end note
    YANKED: Battery removed
    note left of YANKED
        Ch and Dch Stop
    end note

    class BAT_ID ready
    class YANKED yanked
    class CHARGED charged
    class DISCHARGED discharged
    class CHARGE, DISCHARGE currentflow
    class DISCHARGE_PAUSE, CHARGE_PAUSE paused

    %% Possible events
    %% disable: Sets the FSM to disabled
    %% init: Initialises the FSM to the initial state
    %% v_jump: > +2V change in battery voltage in 300ms
    %% v_drop: > -2V change in battery voltage in 500ms (this rate is slower)
    %% ch_jump: > +200mA change in charge current in 100ms
    %% ch_drop: > -200mA change in charge current in 100ms
    %% dch_jump: > +200mA change in discharge current in 100ms
    %% dch_drop: > -200mA change in discharge current in 100ms
    %% ch_done: ?? Not sure how to know charge is completed yet
    %% dch_done: ?? Not sure how to know discharge is completed yet
    %% charge: Start charge by switching on the MOSFET switched on
    %% discharge: Start discharge by switching on the MOSFET switched on
    %% pause: Pause charging or discharging. Turn off MOSFET
    %% resume: Resume charging or discharging. Turn on MOSFET
    %% reset: Resets monitor after yank
    %% get_id: Event to indicate weare getting user input for the ID
    %% set_id: ID input complete and battery ID has been set.
    %% reset_metrics: Resets the metrics for a battery after halting charge/dischare

    %% If ANY input ADCs are not available we are disabled with nowhere
    %% to transition to
    [*] --> DISABLED: disable

    %% Start off assuming we have no battery installed
    [*] --> NOBAT: init

    %% Battery inserted
    NOBAT --> BAT_NOID: v_jump
    %% Battery removed while in BAT_NOID
    BAT_NOID --> YANKED: v_drop

    %% Getting the battery ID
    BAT_NOID --> GET_ID: get_id
    %% Yank while getting the ID
    GET_ID --> YANKED: v_drop

    %% Set ID from user input
    GET_ID --> BAT_ID: set_id
    %% Yank
    BAT_ID --> YANKED: v_drop

    %% Start Charging
    BAT_ID --> CHARGE: charge
    %% Yank
    CHARGE --> YANKED: ch_drop

    %% Pausing the charge
    CHARGE --> CHARGE_PAUSE: pause
    %% Continue charging
    CHARGE_PAUSE --> CHARGE: resume
    %% Reset metrics
    CHARGE_PAUSE --> BAT_ID: reset_metrics
    %% Yank
    CHARGE_PAUSE --> YANKED: v_drop

    %% Charge complete
    CHARGE --> CHARGED: ch_done
    %% Yank
    CHARGED --> YANKED: v_drop
    %% Reset metrics
    CHARGED --> BAT_ID: reset_metrics

    %% Start Discharging
    BAT_ID --> DISCHARGE: discharge
    %% Yank
    DISCHARGE --> YANKED: dch_drop
    
    %% Pausing the discharge
    DISCHARGE --> DISCHARGE_PAUSE: pause
    %% Continue discharging
    DISCHARGE_PAUSE --> DISCHARGE: resume
    %% Reset metrics
    DISCHARGE_PAUSE --> BAT_ID: reset_metrics
    %% Yank
    DISCHARGE_PAUSE --> YANKED: v_drop

    %% Discharge complete
    DISCHARGE --> DISCHARGED: dch_done
    %% Yank
    DISCHARGED --> YANKED: v_drop
    %% Reset metrics
    DISCHARGED --> BAT_ID: reset_metrics

    %% Reset after yank
    YANKED --> NOBAT: reset

    %% Auto reset from yanked if battery is inserted again
    YANKED --> BAT_NOID: v_jump
```

See the [code] and [api-docs] for more details.

This state diagram was also converted to a [DrawIO] diagram and saved a [PNG].

<!-- Links -->
[state diagram]: https://mermaid.js.org/syntax/stateDiagram.html
[FSM]: https://en.wikipedia.org/wiki/Finite-state_machine
[code]: ./Firmware/src/lib/bat_controller.py
[api-docs]: doc/firmware-api/src.lib.bat_controller.StateMachine.html
[DrawIO]: https://app.diagrams.net/
[PNG]: doc/design/BC_StateMachine.drawio.png
[vim-modeline]: # ( vim: set nofoldenable: )
