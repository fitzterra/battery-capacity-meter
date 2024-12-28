# Simple Makefile to make it easier to code, compile and test
#

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

# The MicroPython bin file for flashing to the device. This is expected to be
# in the local dir and called micropython_esp8266.bin or micropython_esp32.bin
# depending on the chip being flashed. Best is to have the correct bin file
# live somewhere else, and symlink this name to the correct file for the
# project and hardware
MPBIN_ESP8266 = micropython_esp8266.bin
MPBIN_ESP32 = micropython_esp32.bin

# Make sure we run build if no target is given on the command line, and not
# erase_flash or some other unintended target.
.DEFAULT_GOAL := build

# Rule to set up the Python requirements using pip - this is just a helper and
# the assumption is that we are in a Python venv currently
pyrequirements:
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

detect_chip:
	@echo "Chip is an $(CHIP)"

# Quick target to detect the current device port, and if found, echo the
# command to set the port to the terminal.
# Uses $MPR to detect all devices, reads them into an array, checks that there
# there is exactly one device, and then echos the export command
detect_device:
	@mapfile -t DEV < <( $(MPR) devs | sed 's/ .*//' ); \
	if [[ $${#DEV[@]} -ne 1 ]]; then echo "Found $${#DEV[@]} devices, while expecting one."; exit 1; fi ;\
	echo -e "Set the current device port with:\n  export DEVICE_PORT=$${DEV[0]}"

erase_flash:
	$(ESPTOOL) --port $(DEVICE_PORT) erase_flash

# Flash the correct binary by first checking what chip we are flashing to.
flash_bin: $(MPBIN)
	chip=$(CHIP); \
	if [[ "$$chip" = "ESP8266" ]]; then \
		$(ESPTOOL) --port $(DEVICE_PORT) --baud 460800 write_flash --flash_size=detect 0 $(MPBIN_ESP8266); \
	elif [[ "$$chip" == "ESP32" || "$$chip" == "ESP32-S2" ]]; then \
		$(ESPTOOL) --port $(DEVICE_PORT) --baud 460800 write_flash -z 0x1000 $(MPBIN_ESP32); \
	else \
		echo "Unknown chip: $$chip"; \
		exit 1; \
	fi


# Python files that need to be cross compiled.
####
# This is for the main application
####
MPY_SRC = boot.py \
		  main.py \
		  i2c_config.py \
		  config.py \
		  structures.py \
		  net_conn.py \
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
		  lib/bat_controller.py \
		  screens.py \
		  version.py \
		  #mqtt.py \
		  #interface.py \

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

# If building the MicroPython binary locally, this is the top level dir of
# where the source has been cloned to from https://github.com/micropython/micropython.git
MP_SRC_DIR = $(wildcard ~/devel/micropython)

# This is the MicroPython port dir for the MP port being build...????
# yadayadayada... better articulation here please...
MP_SRC_PORT_DIR = $(MP_SRC_DIR)/ports/esp8266

# Modules that will be compiled in the firmware if building the MicroPython
# firmware locally. This is especially useful for ESP8266 that has limit
# runtime storage
#MP_SRC_MODULES = lib/ulogging.py \
#				 lib/typing.py \
#				 lib/utils.py \
#				 lib/ulogging.py \
#				 lib/uencoder.py \
#				 lib/ubutton.py \
#				 lib/mqtt_as.py \
#				 ui/ui_input.py \
#				 ui/ui_output.py \
#				 ui/ui_menu.py \
#		  		 ui/ui_field_edit.py \
#				 interface.py \
#				 screens.py \

# Determine the symlinked names of the MP source modules we want to bake into
# the MP binary as frozen modules from the MP_SRC_MODULES list above.
# If uses `notdir` to strip the dirnames from the source paths, then
# substitutes the MP_SRC_PORT_DIR directory name, and it's modules dir, for
# each file to end up with a list of file names that should be the symlinks we
# want to freeze.
MP_SRC_MOD_SYMLINKS = $(patsubst %.py,$(MP_SRC_PORT_DIR)/modules/%.py,$(notdir $(MP_SRC_MODULES)))

# These are any static files we need to minify and upload
STATIC_SRC_MINIFY = 

# We will minimise them before upload, so work out the minimized name
STATICS_MIN = $(patsubst %,%.min,$(wildcard $(STATIC_SRC_MINIFY)))

# This is for the minified versions of the static files.
# We minimise them and leave them with a .min extension alongside the original,
# and then copy the minified version to the firmware dir for upload, but
# without the .min extension. We also gzip compress all these static files to
# save memory when we serve these later.
#
# Using the .min extension version allows make to see when a "compile" is
# needed, and then using the not .min extension in firmware means we do not
# have to change the names of the files in index.html for example.
%.min: %
	@# Minify it.
	$(SCRIPTS)/minify.sh $< > $@
	@# Make any parent dirs in firmware dir
	@mkdir -p $(FW_DIR)/$(@D)
	@# Copy gziped to firmware dir
	gzip -9 -c $@ > $(FW_DIR)/$<

# These are static images we want to upload. They must be in the static dir.
# The only static images files types supported currently is .png and .jpg
STATIC_IMG = 


# These are the targets in firmware/static made from the list in STATIC_IMG to
# be used as dependencies for images to be copied.
ALL_IMG = $(addprefix firmware/,$(STATIC_IMG))

# Rule to copy PNGs from static to firmware dir
firmware/static/%.png: static/%.png
	@cp -vf $< $@

# Rule to copy JPGs from static to firmware dir
firmware/static/%.jpg: static/%.jpg
	@cp -vf $< $@


build: $(MPYS) $(STATICS_MIN) $(ALL_IMG)
	@echo Building...

clean:
	@rm -vf $(MPYS)
	@rm -vrf $(FW_DIR)
	@rm -vf static/*.min
	@find . -name "*.mpy" -exec rm -v {} \;

# For devices with enough memory, like the ESP32 for eg., we do not need to
# freeze the MP_SRC_MODULES into the MicroPython firmware. This target will
# create symlinks for each of these modules in the local dir which will then be
# uploaded directly to the device. See the clean_local_modules to remove these
# again.
local_modules:
	@echo Linking all required modules for local inclusion...
	@for m in $(realpath $(MP_SRC_MODULES)); do ln -vsf $$m; done

clean_local_modules:
	@echo Removing locally linked modules...
	@for m in $(notdir $(MP_SRC_MODULES)); do if [[ -L $$m ]]; then rm -fv $$m; else echo "Not a symlink: $$m"; fi; done

clean_pyboard:
	$(RS) rm -rf /pyboard/*

# This rsyncs the $(FW_DIR) to the /pyboard/ dir
upload: build
	$(RS) rsync -m $(FW_DIR) /pyboard

# Shortcut to see all files in fs root on the board
ls_pyboard:
	$(RS) ls -l /pyboard

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
	@echo MicroPython Source dir: $(MP_SRC_DIR)
	@echo MicroPython Modules to symlink: $(MP_SRC_MODULES)
	@echo MicroPython Modules symlink files: $(MP_SRC_MOD_SYMLINKS)
	@echo Minified static files: $(STATICS_MIN)

repl:
	$(MPR) repl

reset:
	# Do a soft reset by sending a CTRL-D via rshell running the REPL
	$(RS) repl '~  ~'

# This runs the serial input mode. See tools.setUARTMode()
serial:
	@# First get the serial flag file on the board
	$(RS) cp serial_uart /pyboard/
	@# Now run a serial terminal instead of the REPL
	miniterm.py $(DEVICE_PORT)  115200

# Rule to build a local copy of the MicroPython binary using the docker base
# for the Espressif build tool chain as per the docs for esp8266 ... Explain
# this better.............. ???????????
build_micropython:
	@echo Cleaning up all old modules...
	@cd $(MP_SRC_PORT_DIR) && make clean-modules
	@echo Linking all required modules to freeze into the MicroPython binary...
	@#NOTE: This uses `cp` to copy the modules to freeze to the remote modules dir,
	@#      creating the same dir structure in the remote, but using harlinks instead
	@#      of copying the again. This means the remote dir should beon the same
	@#      filesystem as the modules to freeze.
	@for m in $(MP_SRC_MODULES); do cp --verbose --link --parents $$m $(MP_SRC_PORT_DIR)/modules/; done
	@echo Builing new MicroPython binary. This may take a while with no output, so hang in there....
	@docker run --rm -v $$HOME:$$HOME -u $$UID -w $(MP_SRC_PORT_DIR) larsks/esp-open-sdk make -j BOARD=ESP8266_GENERIC
	@ln -vfs $(MP_SRC_PORT_DIR)/build-ESP8266_GENERIC/firmware.bin micropython_esp8266.bin

# Builds the docs using pydoctor. Requires the pydoctor python package to have
# been installed, and also a fully configured pydoctor.ini or similar config
# file for pydoctor
docs:
	@# First determine remote gitlab url from the git remote,
	@# and also the current branch. This is used to set the
	@# source URL for the docs
	@remote_url=$$(git config --get remote.origin.url) && \
	branch_name=$$(git branch --show-current) && \
	if [[ $$remote_url == git@* ]]; then \
	  remote_url=$$(echo "$$remote_url" | sed -e 's/:/\//' -e 's/^git@/http:\/\//'); \
	fi && \
	if [[ $$remote_url == *.git ]]; then \
	  remote_url=$${remote_url%.git}; \
	fi && \
	html_url="$$remote_url/blob/$$branch_name/Firmware/src" && \
	pydoctor --project-url "$$remote_url" --html-viewsource-base "$$html_url" --template-dir=./pydoctor_templates
