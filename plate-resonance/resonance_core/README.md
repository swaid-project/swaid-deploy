# Resonance Core

The central resonance calculation engine for the SWAID Plate Resonance project.

## Repository Structure

- `include/`: Header files (`.hpp`)
- `src/`: Source files (`.cpp`)
- `test/`: Python-based testing scripts (`core_tester.py`)
- `third_party/`: Local dependencies managed by setup script
- `build/`: Compiled binaries and build artifacts

## Build Environment

### 1. Fetch Dependencies
Initialize the local environment by running the setup script:
```bash
./setup_dependencies.sh
```

### 2. Compilation
Compile the project using CMake:
```bash
cd build
cmake ..
make
```

The compiled `resonance_core` executable will be placed in the `build/` directory.
