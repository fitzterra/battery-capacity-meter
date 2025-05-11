Runtime Config Backup
=====================

This directory is used during development to backup any runtime configs before
deploying new firmware, and then restoring the configs again.

The `site_local.py` config system makes it very easy to split the total config as
Python files over multiple separate config files.

The UI then allows changing certain settings from any of these config files
which then uses the site local config system to store a new config file with
`_local.py` appended to original file that contains the config option being
changed.

This is great for runtime, but since the Makefile upload function is done such
that it only uploads files that are specifically designated as firmware files,
and deletes any files off the device that should not be there, this is a
problem with local runtime config files. These are deleted when new firmware is
deployed, making the development life cycle more difficult since the runtime
config often contains calibration info that needs to be redone after a firmware
deployment.

To solve this problem, there is a target for backing up all files that end win
`_local.py` before deploying new firmware, and then restoring these config
files again after deployment.

This `runtime_conf` dir is there to allow the backups to be done.

It has these sub directories that are not version controlled:

`backup`: This is used to store the config files before deploying new firmware,
and then restoring to the device after deployment

`source`: This is just a general place that can be used to store local copies
of any config files for posterity. Let's say you have a config file that
contains WiFi creds for example and there is a concern that you somehow loose
these for a deployment that fails, this is a good place to store that runtime
config file. Things can go wrong with deployments and the only place where t he
runtime configs are kept are on the device, so if these are important to keep,
make copies of them in this dir after doing a `make runtime_cfg_backup` - the
runtime configs will be in the `backup` dir.
