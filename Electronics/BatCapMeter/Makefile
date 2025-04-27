# Makefile to perform various repeatable action on a Schematic or PCB

# Always use one shell for recipes
.ONESHELL:

PCB_EXT := .kicad_pcb

# Use shell command to find the project base file name Using the PCB extension
PROJ_BASE := $(shell basename -s $(PCB_EXT) $$(ls *$(PCB_EXT) 2>/dev/null) 2>/dev/null)

PCB_FILE := $(PROJ_BASE)$(PCB_EXT)

# File names for back and front Toner Transfer PDFs
BACK_TT_PDF := $(PROJ_BASE)-tt-back.pdf
FRONT_TT_PDF := $(PROJ_BASE)-tt-front.pdf
BACK_SMD_PDF := $(PROJ_BASE)-smd-back.pdf

# KiCAD command shorteners
CMD_PDF := kicad-cli pcb export pdf

# This is a PDF for Toner Transfer local PCB making.
# It includes the bottom copper layer and the board edges
$(BACK_TT_PDF): $(PCB_FILE)
	@echo "Creating back layers PDF: $@ ..."
	$(CMD_PDF) --black-and-white --drill-shape-opt 1 --layers B.Cu,Edge.Cuts --output $@ $<

# This is a PDF for Toner Transfer the top side of a single sided PCB.
# This includes any routes added to the front copper layer which must be
# replaced with jumper wires and the rest of the front Cu detail. It also
# includes the board edges, the front silkscreen, front Fab and User.1 layers
# to show the component outlines and names.
$(FRONT_TT_PDF): $(PCB_FILE)
	@echo "Creating back layers PDF: $@ ..."
	$(CMD_PDF) --mirror --black-and-white --drill-shape-opt 1 --layers F.Cu,Edge.Cuts,F.Silkscreen,F.Fab,User.1 --output $@ $<

# Placement for Back Copper side SMDs
$(BACK_SMD_PDF): $(PCB_FILE)
	@echo "Creating back SMD placemkent PDF: $@ ..."
	$(CMD_PDF) --mirror --black-and-white --drill-shape-opt 1 --layers Edge.Cuts,B.Silkscreen,B.Mask,B.Fab --output $@ $<


# Rile to make all Toner Transfer PDFs
toner-pdfs: $(BACK_TT_PDF) $(FRONT_TT_PDF) $(BACK_SMD_PDF)
	@echo "Toner Transfer PDF files created."

# Cleans up all Toner Transfer PDFs
clean-toner-pdfs:
	rm -f $(BACK_TT_PDF) $(FRONT_TT_PDF) $(BACK_SMD_PDF)

# Just shows some config and helps to debug
conf:
	@echo "PROJ_BASE: $(PROJ_BASE)"
	echo "Toner Transfer for back Cu: $(BACK_TT_PDF)"
	echo "Toner Transfer for front Cu: $(FRONT_TT_PDF)"
	echo "Back SMD placment: $(BACK_SMD_PDF)"
