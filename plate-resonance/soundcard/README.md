# Soundcard Driver

Real-time audio processing and signal generation for the SWAID Plate Resonance project.

## Repository Structure

- `include/`: Header files (`.hpp`)
- `src/`: Implementation files
- `test/`: Python-based testing scripts
- `third_party/`: Local dependencies (e.g., ImGui) managed by setup script
- `build/`: Compiled binaries and build artifacts

## Build Environment

### 1. System Dependencies
Ensure you have the required audio and windowing libraries installed:
```bash
sudo apt install portaudio19-dev
```

### 2. Fetch Local Dependencies
Initialize the local environment by running the setup script:
```bash
./setup_dependencies.sh
```

### 3. Compilation
Compile the project using CMake:
```bash
cd build
cmake ..
make
```

The compiled `rx_driver` executable will be placed in the `build/` directory.
