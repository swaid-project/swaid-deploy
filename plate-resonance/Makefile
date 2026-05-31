# SWAID Plate Resonance - Modern Makefile

.PHONY: all clean setup

all:
	mkdir -p build
	cd build && cmake .. && make -j$(nproc)

setup:
	@echo "All dependencies are now managed by CMake FetchContent."
	@echo "Just run 'make all' to build everything."

clean:
	@echo "Cleaning build folder..."
	rm -rf build
