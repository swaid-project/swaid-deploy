# SWAID Plate Resonance - Global Makefile

.PHONY: all sdk core tuner sim clean setup

all: sdk core tuner sim

setup:
	chmod +x setup_dependencies.sh
	./setup_dependencies.sh

sdk:
	@echo "Building Resonance SDK..."
	cd resonance_sdk/build && cmake .. && make

core: sdk
	@echo "Building Resonance Core..."
	cd resonance_core/build && cmake .. && make

tuner: sdk
	@echo "Building Resonance Tuner..."
	cd resonance_tuner/build && cmake .. && make

sim:
	@echo "Building Chladni Simulator..."
	cd simulator/build && cmake .. && make

clean:
	@echo "Cleaning all build folders..."
	rm -rf resonance_sdk/build/*
	rm -rf resonance_core/build/*
	rm -rf resonance_tuner/build/*
	rm -rf simulator/build/*
