.PHONY: all core ui clean run

# Build everything
all: core ui

# Build the C++ Server
core:
	@echo "=== Building Plate Resonance Core ==="
	@cd plate-resonance && mkdir -p build && cd build && cmake .. && make -j4

# Build the Python Client
ui:
	@echo "=== Building Human Interface ==="
	@cd human-interface && chmod +x build_client.sh && ./build_client.sh

# Clean both builds
clean:
	@echo "=== Cleaning all builds ==="
	@rm -rf plate-resonance/build
	@rm -rf human-interface/dist
	@rm -rf human-interface/build
	@rm -rf human-interface/__pycache__

# Shortcut to launch the system
run:
	@chmod +x swaid_launcher.sh && ./swaid_launcher.sh
