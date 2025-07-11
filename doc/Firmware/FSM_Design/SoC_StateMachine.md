SoC Measure State Machine
=========================

Below is a [state diagram] that governs the [FSM] for measuring SoC for a given
Battery Controller.

```mermaid
---
title: SoC Measurement State Diagram
---

stateDiagram-v2
    direction TB

    classDef error fill:#a44,color:white,font-weight:bold,stroke-width:2px,stroke:#700
    classDef charging fill:#4a4,color:white,font-weight:bold,stroke-width:2px,stroke:#070
    classDef discharging fill:#d50,color:white,font-weight:bold,stroke-width:2px,stroke:#a20
    classDef resting fill:#036,color:white,font-weight:bold,stroke-width:2px,stroke:#059
    classDef canceled fill:#770,color:white,font-weight:bold,stroke-width:2px,stroke:#330
    classDef completed fill:#336,color:white,font-weight:bold,stroke-width:2px,stroke:#559

    
    %% Possible states and actions to perform when
    %% Transitioning to that state.
    READY: Ready
    CHARGING_1ST: Initial Charge
    note left of CHARGING_1ST
        num_cycles = 0
    end note
    CHARGING: Charging
    REST_CH: Rest post charge
    note right of REST_CH
        num_cycles++
    end note
    DISCHARGING: Discharging
    REST_DCH: Rest post discharge
    COMPLETE: SoC Complete
    CANCEL: SoC Canceled
    ERROR: Error

    class ERROR error
    class CHARGING, CHARGING_1ST charging
    class DISCHARGING discharging
    class REST_CH, REST_DCH resting
    class CANCEL canceled
    class COMPLETE completed

    [*] --> READY

    %% Unexpected Battery Controller state goes to error
    READY --> ERROR: unexpected BC state
    CHARGING_1ST --> ERROR: unexpected BC state
    CHARGING --> ERROR: unexpected BC state
    DISCHARGING --> ERROR: unexpected BC state
    REST_CH --> ERROR: unexpected BC state
    REST_DCH --> ERROR: unexpected BC state

    %% Cancel at any stage
    CHARGING_1ST --> CANCEL: cancel
    CHARGING --> CANCEL: cancel
    DISCHARGING --> CANCEL: cancel
    REST_CH --> CANCEL: cancel
    REST_DCH --> CANCEL: cancel

    %% Manual error reset
    ERROR --> [*]

    %% Start SoC measurement
    READY --> CHARGING_1ST: charge

    %% Rest after 1st charge
    CHARGING_1ST --> REST_CH: charge complete

    %% Starting the cycle

    %% Discharge
    REST_CH --> DISCHARGING: discharge

    %% Fully discharging
    DISCHARGING --> REST_DCH: discharge complete

    %% Charge cycle
    REST_DCH --> CHARGING: charge

    state CycleComplete <<choice>>

    %% Charge complete
    CHARGING --> CycleComplete: charge complete
    CycleComplete -->  REST_CH: num_cycles < max_cycles, charge complete
    CycleComplete -->  COMPLETE: num_cycles == max_cycles, cycle complete

    %% Exit after SoC Complete or Canceled
    COMPLETE --> [*]
    CANCEL --> [*]
```


See the [code] and [api-docs] for more details.

This state diagram was also converted to a [DrawIO] diagram and saved a [PNG].

<!-- Links -->
[state diagram]: https://mermaid.js.org/syntax/stateDiagram.html
[FSM]: https://en.wikipedia.org/wiki/Finite-state_machine
[code]: ./Firmware/src/lib/statemachines.py
[api-docs]: doc/firmware-api/src.lib.bat_controller.StateMachine.html
[DrawIO]: https://app.diagrams.net/
[PNG]: doc/design/SoC_StateMachine.drawio.png
[vim-modeline]: # ( vim: set nofoldenable: )
