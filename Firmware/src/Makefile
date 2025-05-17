# Simple Makefile to make it easier to code, compile and test
#

# This brings in all the user defines MCU config bits.
include MCU_CONF

SHELL = /bin/bash

# Override this from the command line to have more verbose output logging with
# the `run` rule.
VERBOSE = 1

# Dir where all support and build scripts are kept
SCRIPTS = ./support_scripts

# The mpy cross compiler to use - default is the one in the path/env
MC = mpy-cross
# The rshell to use for managing the board. Expected rshell to be configured
# via environment to use the port already.
RS = rshell
# The esptool to use for flashing, etc. - default is to use the one in the path/venv
ESPTOOL = esptool.py

# The mpremote tool
MPR = mpremote

# Firmware dir for flashing to mcu
FW_DIR=firmware

# The backup directory to use for runtime config files that are copied off the
# device before doing a firmware upload.
# The reason for this is that the runtime config as created directly on the
# device by changing parameters in the config options.
# These actions creates *_local.py runtime config files on the device, but they
# are not listed in $MPY_SRC, so when we upload these *._local.py files are
# removed.
# By first backing them up via the `runtime-cfg-backup` target, then doing the
# upload, and afterwards copying them all back to the device, we can preserver
# local config during development.
RT_BACKUP_DIR=./runtime_conf/backup

# These variables are for fetching and flashing the MicroPython binary. The
# defaults are defined in MCU_CONF which we include above.
# Dir into which we will download the MP_BIN binary. Will create it if it does
# not exist, and should be added to .gitignore
MP_BIN_DIR := micropython_binary
# The path to the MicroPython binary we will download if it does not exist
MP_BIN_PATH := $(MP_BIN_DIR)/$(MP_BIN)

.PHONY = help show-mcu-conf dev-env \
	     detect-chip detect-device erase-flash flash-bin build \
	     runtime-cfg-backup upload run clean conf repl reset docs 

# Make sure we run build if no target is given on the command line, and not
# erase-flash or some other unintended target.
.DEFAULT_GOAL := build

# A help message ALA heredoc style for makefiles. It depends on the GNU make
# and it multiline variables. See: https://unix.stackexchange.com/a/516476
define help_msg =

The following make targets are available:

dev-env             - Sets up the local development environmetn
show-mcu-conf       - Show details on the MCU as defined in the MCU_CONF file
detect-chip         - Detects the chip on the connected device
detect-device       - Detects the device or port the device is connected on
erase-flash         - Erases the flash on the device - require before flash-bin
flash-bin           - Flashes the Python binary to the device
build               - Builds the firmware
upload              - Uploads the firmware - will do a build if needed
runtime-cfg-backup  - Backs up runtime config off the device - auto done before upload
clean:              - Cleans firmware and all .mpy files found
repl                - Connects to device and runs a REPL
docs                - Buils the applications docs
run                 - Build, uploads and the ndoes a soft reset to run the new firmware
conf                - Show some config settings
reset               - Does a soft reset to the connected device

endef

# Show the help_msg defined above. To break this down for those not 100%
# familiar with Makefile Syntax:
# * The ; after help: allows you to define the recipe inline on the same line.
# * @ suppresses echoing the command before execution (as usual in Make).
# * $(info ...) is a Make built-in function. It is evaluated by Make itself,
#   not by the shell. It prints the message to stdout at parse time, not run time.
# * The : at the end does nothing in the shell — it is a shell built-in no-op.
#   It's just there to ensure the line has a command that returns true.
help:; @ $(info $(help_msg)) :

# A multiline message to give details on the MCU config
define mcu_conf =

MCU Config:

---DEV Board---
DBOARD_MANUFACTURER: $(DBOARD_MANUFACTURER)
DBOARD_MODEL:        $(DBOARD_MODEL)
DBOARD_SITE:         $(DBOARD_SITE)
DBOARD_FLASH_MODE:   $(DBOARD_FLASH_MODE)

---MCU Info----
MCU_MANUFACTURER: $(MCU_MANUFACTURER)
MCU_MODEL:        $(MCU_MODEL)
MCU_DATASHEET:    $(MCU_DATASHEET)

---MicroPython Info---
MP_DOWNLOAD_SITE: $(MP_DOWNLOAD_SITE)
MP_BIN:           $(MP_BIN)
MP_BIN_URL:       $(MP_BIN_URL)

endef

# Displays the mcu_conf message. See the help target above for syntax info.
show-mcu-conf:; @ $(info $(mcu_conf)) :

# Rule to set up the Python development requirements using pip - this is just a
# helper and the assumption is that we are in a Python venv currently
dev-env:
	pip install -r requirements.txt

#======================
# Flashing Micropython to the device
# NOTE: The port to use is expected in the environment variable DEVICE_PORT.
# Best is to set this up using direnv or similar for now.
# 
# See here for more: http://docs.micropython.org/en/latest/esp8266/tutorial/intro.html#intro

# Detect the type of chip by parsing the output from the flash_id command.
# NOTE: This will only be run when CHIP is expanded, which is good if we want
# to run a command that does not need to know the chip. It is bad, however when
# we need to test for more than two types of chip. The reason is how make
# variables are defined and how it is not possible to assign make variables
# from within a rule, but controlling when we execute this command is only
# viable from a rule... messy business, or else I do not understand things too
# well yet.
CHIP = $(shell $(ESPTOOL) --port $(DEVICE_PORT) flash_id | grep "^Detecting chip.*ESP" | sed 's/.*\(ESP[0-9]\+\)/\1/')

detect-chip:
	@echo "Chip is an $(CHIP)"

# Quick target to detect the current device port, and if found, echo the
# command to set the port to the terminal.
# Uses $MPR to detect all devices, reads them into an array, checks that there
# there is exactly one device, and then echos the export command
detect-device:
	@mapfile -t DEV < <( $(MPR) devs | sed 's/ .*//' ); \
	if [[ $${#DEV[@]} -ne 1 ]]; then \
		echo "Found $${#DEV[@]} devices, while expecting one."; \
		exit 1; fi ;\
	echo -e "Set the current device port with:\n  export DEVICE_PORT=$${DEV[0]}"

# Download the Micropython binary if it does not already exist.
$(MP_BIN_PATH):
	@mkdir -p $(MP_BIN_DIR)
	@echo "Downloading $(MP_BIN_URL) to $@"
	@curl -L -o $@ $(MP_BIN_URL)

erase-flash:
	$(ESPTOOL) --port $(DEVICE_PORT) erase_flash

# Flash the binary - we only support ESP32 for this project
flash-bin: $(MP_BIN_PATH)
	$(ESPTOOL) --port $(DEVICE_PORT) --baud 460800 write_flash -z 0x1000 $(MP_BIN_PATH) 
	@echo "Flash complete. You may need to press reset on the board."

# Python files that need to be cross compiled.
# All files listed here will be added to the firmware (after cross compiling)
# and uploaded to the device. If you need any python file, module or lib in the
# firmware, this is where to add it.
MPY_SRC = boot.py \
		  main.py \
		  sitelocal_conf.py \
		  net_conf.py \
		  i2c_config.py \
		  config.py \
		  shunt_conf.py \
		  structures.py \
		  telemetry.py \
		  ui/__init__.py \
		  ui/ui_input.py \
		  ui/ui_output.py \
		  ui/ui_menu.py \
		  ui/ui_field_edit.py \
		  lib/ulogging.py \
		  lib/led.py \
		  lib/ssd1306.py \
		  lib/ads1x15.py \
		  lib/utils.py \
		  lib/uencoder.py \
		  lib/ubutton.py \
		  lib/adc_monitor.py \
		  lib/statemachines.py \
		  lib/bat_controller.py \
		  lib/mqtt_as.py \
		  lib/uuid.py \
		  screens.py \
		  version.py \

# The expected .mpy files for each .py above
MPYS = $(patsubst %.py,%.mpy,$(wildcard $(MPY_SRC)))

# These are files that should not be compiled before going into the firmware
PY_SRC = boot.py main.py

# Rule to cross compile source python files.
# NOTE: To detect changes in files, all files that needs to go into the firmware
# dir should be in $MPY_SRC - This will cause the compile rule below to be
# executed for that file if it changes.
# The compile step will also copy the compiled file to the $FW_DIR tree to
# rsync to the MCU filesystem.
# Any source files that should go onto the MCU file system without being
# compiled (like boot.py for example), should be listed in $PY_SRC. These will
# be detected on change due to being in $MPY_SRC, and will be compiled, but the
# compiled version will not be copied to the firmware dir, but rather the
# source version.
%.mpy: %.py
	@# Cross compile
	$(MC) -v $<
	@# Make any parent dirs in firmware dir
	@mkdir -p $(FW_DIR)/$(@D)
	@# Copy the compiled or source file to the firmware dir
	@if $$(grep -q "$<" <<< "$(PY_SRC)"); then \
		cp $< $(FW_DIR)/$< ; \
	else \
		cp $@ $(FW_DIR)/$@ ; \
	fi

build: $(MPYS)
	@echo Building...

clean:
	@rm -vf $(MPYS)
	@rm -vrf $(FW_DIR)
	@find . -name "*.mpy" -exec rm -v {} \;

# Backup all *_local.py files on the device to 
# NOTES:
# 	* mpremote does not support wildcard copies as v1.23.0
# 	* mpremote adds \r line endings for stupid Windblows, so we need to remove
# 	  these with the 's/\r//' sed command or else they stay in the file name.
# 	* Since we run a pipeline with the mpremote output, we can not start
# 	another mpremote command to do the copying in the while read loop. Instead
# 	we touch the file names we need to copy in the backup dir, effectively
# 	making a list of files, and the we copy then in a separate process.
runtime-cfg-backup:
	@echo "Backing up runtime configs..."
	@# First clean up
	@rm -rf $(RT_BACKUP_DIR)/*
	@# Touch a file for each of the ones we will be backing up in RT_BACKUP_DIR
	@$(MPR) ls : \
		| sed -e 's/\r//' -e 's/.\+[0-9] //' \
		| grep "_local\.py" \
		| while read f; do \
			echo "  [$${f}]"; \
			touch $(RT_BACKUP_DIR)/$${f} ; \
		  done
	@# Now construct the mpremote cp command to copy all filenames we have
	@# in RT_BACKUP_DIR from the remote back to RT_BACKUP_DIR
	@(\
		REMS=$$(ls -x $(RT_BACKUP_DIR)/ | sed 's/  / :/g'); \
		if [[ -n $$REMS ]]; then \
			$(MPR) cp  :$$REMS $(RT_BACKUP_DIR)/; \
		fi \
	 )

# This rsyncs the $(FW_DIR) to the /pyboard/ dir and then resotes any runtime
# configs
upload: build runtime-cfg-backup
	$(RS) rsync -m $(FW_DIR) /pyboard
	@echo "Restoring runtime configs..."
	$(MPR) cp $(RT_BACKUP_DIR)/* :

# Run the updated firmware after compiling and uploading changes, then doing a
# soft reboot via the REPL
run: upload
	# Now a soft reset by sending a CTRL-D
	$(RS) repl '~  ~'

conf:
	@echo Source: $(MPY_SRC)
	@echo Compiled .mpy  for firmware: $(MPYS)
	@echo Source .py for firmware: $(PY_SRC)
	@echo Firmware dir: $(FW_DIR)
	@echo Minified static files: $(STATICS_MIN)

repl:
	$(MPR) repl

reset:
	# Do a soft reset by sending a CTRL-D via rshell running the REPL
	$(RS) repl '~  ~'

# Dynamically symlink all known images from the main docs dir to a local img
# dir inside this src dir. This is needed so that any images referred to in the
# docs are all contained in this dir tree. Without this, when we build the docs
# for GitLab pages, we will copy the full img dir as actual files in order to
# make all images work in the docs.
doc_img:
	@# Remove all current symlinks
	@rm -rf img
	@mkdir img
	@# Create symlinks to all available images in docs/ dir
	@cd img; \
	for i in ../../../doc/Electronics/*.{png,jpg,jpeg,svg,gif}; do\
		[[ ! -f $$i ]] && continue; \
		ln -s $$i; \
	done; \
	for i in ../../../doc/Firmware/{FSM_Design,Screen_Design}/*.{png,jpg,jpeg,svg,gif}; do\
		[[ ! -f $$i ]] && continue; \
		ln -s $$i; \
	done

# Builds the docs using pydoctor. Requires the pydoctor python package to have
# been installed, and also a fully configured pydoctor.ini or similar config
# file for pydoctor
docs: doc_img
	@# First determine remote gitlab url from the git remote,
	@# and also the current branch. This is used to set the
	@# source URL for the docs
	@remote_url=$$(git config --get remote.origin.url) && \
	branch_name=$$(git branch --show-current) && \
	if [[ $$remote_url == git@* ]]; then \
	  remote_url=$$(echo "$$remote_url" | sed -e 's/:/\//' -e 's/^git@/https:\/\//'); \
	fi && \
	if [[ $$remote_url == *.git ]]; then \
	  remote_url=$${remote_url%.git}; \
	fi && \
	html_url="$$remote_url/blob/$$branch_name/Firmware/src" && \
	pydoctor --project-url "$$remote_url" --html-viewsource-base "$$html_url" \
		--template-dir=./pydoctor_templates
	@#We need to now symlink the local img dir to the docs output dir - A bit
	@# messy here with these hardcoded dirs, but should be easy to spot if it
	@# breaks.
	@cd ../../doc/firmware-api && ln -sf ../../Firmware/src/img

