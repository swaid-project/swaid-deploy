# LED Driver

Firmware for controlling the LED feedback system on the SWAID Plate.

## Repository Structure

- `include/`: Header files (`embedded_sal.hpp`)
- `src/`: Implementation files (`embedded_sal.cpp`, `.ino` files)
- `test/`: Python-based testing scripts (`test_pico_led.py`)
- `third_party/`: Local dependencies managed by setup script
- `build/`: Compiled binaries and build artifacts

## Build Environment

This module is designed for the Raspberry Pi Pico and can be built using either CMake or PlatformIO.

### 1. Fetch Dependencies
Initialize the local environment by running the setup script:
```bash
./setup_dependencies.sh
```

### 2. Compilation (CMake)
```bash
cd build
cmake ..
make
```

### 3. Compilation (PlatformIO)
If you prefer PlatformIO:
```bash
pio run
```
