"""
Python module to make it easier to add site local configs.

Introduction
------------

Any project or system configs often consists of a number of config values which
broadly falls into two categories:

* **General config values**: These are often config values which are used to
  avoid having hardcoded values in the code, like file names, specific module
  config values, etc. These are usually sane values and does not change per
  deployment site.
* **Site local values**: These are config values that are set specific for the
  site or point of deployment. These are things like passwords, local host
  names, or user tweaked configs.

This module and config definition proposed here provides interfaces to make it
easy to have the general config and site local values (using defaults) in one
config file, but then allow site local values to be updated and stored locally,
and to have these overwrite the default values at run time.

Config setup
------------

The idea is that any config file can be made to read site local overrides.

See:
    `Site local config at runtime`_ below for how to create the site local
    override files at runtime.

Create your config file as a Python module with the config values as global
constants in the config file, for example the file ``config.py`` may look like
this:

.. python::
     
    '''
    System config
    '''
    from sitelocal_conf import overrideLocal

    # This set the size of the foober
    FOO = 22

    # The things we need to set up the barrer function. Do not change this
    # unless you klnow what you're doing
    BAR_LOOPS = 4
    BAR_DIR = "left"

    # The local site name - this will be overridden from the site local config
    SITE = ""

    # The time to run the daily report
    REP_TIME = "00:04"

    # Override any site local values
    overrideLocal(__name__, locals())


When this config is imported by the application, it will set all default
values, and then call `overrideLocal()` with the local config module name, and
the local file namespace. The `overrideLocal()` function with then to try to
import a file with the same name as the module name, but with ``_local``
appended.

It will import all (``*``) from this local file, which will then override all the
local values passed in from the config file.

See the next section for how to create the site local config.

Site local config at runtime
----------------------------

In order to make it easy to create site local config overrides for any config
module, the `updateLocal()` function can be used.

The idea is to call this function, passing names for variables to save as site
local variables, as well as the config module to which this applies.

Assuming the default config module is ``config.py`` and looks like this:

.. python::

    from sitelocal_conf import overrideLocal

    USERNAME = ""
    USERPASS = ""

    FROBBER_HOST = "frobber.com"

    # Override any site local values
    overrideLocal(__name__, locals())

It stores the access credentials to the default Frobber host, but the access
creds are not known until runtime where a UI is available for the user to
supply the creds.

Once this is done, the access creds should be stored locally as site local
values and override the defaults whenever the config is imported. The last line
already does this as explain in the `Config setup`_ section above.

The easiest way to store the site local values is to use the `updateLocal()`
function.

Assume there is some UI module that has a function that receives the username
and password from the user, and then needs to store it locally:

.. python::

    '''UI module'''
    import config
    from sitelocal_conf import updateLocal

    # lots of UI stuff here ....

    def saveCreds(user, pass):
        '''
        Save user creds locally.
        '''
        # First update it in config which will make it available to anything
        # else that have imported config.
        config.USERNAME = user
        config.PASSWORD = pass

        # Now save these two vars locally for the `config` module.
        updateLocal(['USERNAME', 'PASSWORD'], config)

When ``saveCreds()`` is called, it first updates the config with the supplied
creds (whatever called this function will expect the creds to have been updated
in ``config`` on return), and then calls `overrideLocal()` which will add those
two credential variables to a ``config_local.py`` file, update them in the file
if it already exists, or create the file if it does not exist.

Warning:
    The following assumptions are made:

    * All config files are in the top level app dir. It does not work for
      config files imported from a package yet, but could be an option to
      explore if needed.
    * New files can be created in the local runtime environment, and there is
      space available to do so.
"""


def overrideLocal(mod: str, mod_locals: dict):
    """
    Function to override any config values in a config module from a site local
    config override module.

    See:
        `Config setup <#rst-config-setup>`_ section above.

    Args:
        mod: The config module name. Easiest is to use the ``__name__``
            atrribute from the module. Say the default config module is called
            ``conf.py`` and it has been imported with ``import conf``, then use
            ``conf.__name__`` for this module name arg.
        mod_locals: The config modules ``locals`` namesapace dict. Just pass the
            config module directly. Assuming the same setup as described above,
            the value for this arg will then just be ``conf``
    """
    # @pylint: disable=exec-used,bare-except
    try:
        local_f = f"{mod}_local"
        exec(f"from {local_f} import *", mod_locals)
    except:
        # Here we could test for file not found or import errors and wearn if there
        # are errors in the local file as opposed to no file at all.
        # For now, we just ignore it.
        pass


def updateLocal(names: str | list, conf_mod):
    """
    Manages site local config overrides for a given config module.

    See:
        The `Site local config at runtime <#rst-site-local-config-at-runtime>`_
        section for more info and an example.

    Args:
        names: A single config name or a list of config names (as strings) from
            ``conf_mod`` module to save as site local values.
        conf_mod: The config module for which the configs defined by ``names``
            should be saved as site local values.
    """
    import os

    # Default names to a list if it is not a list or tuple
    if not isinstance(names, (list, tuple)):
        names = [names]

    # If we are here, globals() seems to be limited to this module, and
    # therefore the vars to make local in names should be in globals()
    to_update = {n: getattr(conf_mod, n) for n in dir(conf_mod) if n in names}
    if not to_update:
        print("Nothing to update.")
    else:
        print(f"Going to update: {to_update}")

    local_f = f"{conf_mod.__name__}_local.py"

    out = ""
    # Get the current local config file contents, replacing all values to
    # update
    if local_f in os.listdir():
        with open(local_f, "r", encoding="utf-8") as cf:
            while ln := cf.readline():
                var = ln.split(" ", maxsplit=1)[0]
                if not var in to_update:
                    out += ln
                else:
                    out += f"{var} = {to_update[var]}\n"
                    del to_update[var]

    # Add anything we did not already update
    for n, v in to_update.items():
        out += f"{n} = {v}\n"

    with open(local_f, "w", encoding="utf-8") as cf:
        cf.write(out)
