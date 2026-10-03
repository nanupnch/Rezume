.DEFAULT_GOAL := build

ENGINE ?= pdflatex
BUILD_DIR ?= build/$(ENGINE)
LATEXMK ?= latexmk
PYTHON ?= python3

ENGINE_FLAG_pdflatex := -pdf
ENGINE_FLAG_xelatex := -xelatex
ENGINE_FLAG_lualatex := -lualatex
ENGINE_FLAG := $(ENGINE_FLAG_$(ENGINE))
ifeq ($(ENGINE_FLAG),)
$(error ENGINE must be pdflatex, xelatex, or lualatex)
endif

.PHONY: build check sample clean

build:
	$(LATEXMK) $(ENGINE_FLAG) -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error -outdir="$(BUILD_DIR)" rezume.tex

check: build
	REZUME_ENGINE="$(ENGINE)" REZUME_BUILD_DIR="$(abspath $(BUILD_DIR))" $(PYTHON) -m unittest discover -s tests -v

sample: build
	cp "$(BUILD_DIR)/rezume.pdf" rezume.pdf
	pdftoppm -jpeg -singlefile -scale-to 1754 "$(BUILD_DIR)/rezume.pdf" rezume-preview

clean:
	$(LATEXMK) $(ENGINE_FLAG) -C -outdir="$(BUILD_DIR)" rezume.tex
