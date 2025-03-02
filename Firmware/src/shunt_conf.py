"""
Config file that contains all shunt resistor values for all battery
controllers.

See the `config.HARDWARE_CFG` for details on these shunt resistors.

We use a separate config file for these so that we can use the `sitelocal_conf`
functionality to dynamically calibrate these shunt values at runtime, and save
them across boots.

Naming Convention
-----------------

The `HARDWARE_CFG` from `config` contains the full configuration for all
available `BatteryController` s. Each BC entry has a name as a string value
which we use here as a way to define the unique config values for the shunt
resistor values.

The format is:

    BCn_[D]CH_R

Where ``n`` is the numeric id for the BC, and ``CH`` indicates this is the
charge shunt (actually this is the TP4056 analog charge current indicator which
we normally set to 1Ω, but also needs calibration), and if it is ``DCH`` it
refers to the discharge shunt or LOAD resistor.

Runtime Calibration
-------------------

Each of these shunts can be calibrated from the ``Config -> Calibration`` menu
which starts the `screens.Calibration` screen.

On saving the calibrated value, this calibration function will save a site
local version of this config file by using the `sitelocal_conf.updateLocal`
function. See `screens.Calibration._saveCalibration` for details.

On import of this file, we will override these default values from any site
local values found that was saved before.

Attributes:
    BC0_CH_R: BC0 shunt resistor value used for charge current calculation
    BC1_CH_R: BC1 shunt resistor value used for charge current calculation
    BC2_CH_R: BC2 shunt resistor value used for charge current calculation
    BC3_CH_R: BC3 shunt resistor value used for charge current calculation

    BC0_DCH_R: BC0 shunt resistor value used for discharge current calculation
    BC1_DCH_R: BC1 shunt resistor value used for discharge current calculation
    BC2_DCH_R: BC2 shunt resistor value used for discharge current calculation
    BC3_DCH_R: BC3 shunt resistor value used for discharge current calculation

"""

from sitelocal_conf import overrideLocal

BC0_CH_R = 1
BC1_CH_R = 1
BC2_CH_R = 1
BC3_CH_R = 1

BC0_DCH_R = 8
BC1_DCH_R = 8
BC2_DCH_R = 8
BC3_DCH_R = 8

# Override any site local values
overrideLocal(__name__, locals())
