# SWAID Plate Resonance Service

This directory contains the C++ backend service for the SWAID (Synchronized Vibroacoustic & Interactive Display) project.

## Overview

The Plate Resonance service is a high-performance hardware orchestrator. It manages real-time DSP for physical vibrations, executes an embedded generative music engine (`libpd`), and synchronizes visual LED feedback.

### **Architectural Paradigm: "Smart Client, Synchronized Core"**
- **Python UI (Smart Client):** The master controller that holds application state and processes user input.
- **C++ Core (Synchronized Hub):** An ultra-fast, low-latency "Dumb Server" that executes real-time tasks with frame-accurate precision.

For a full technical breakdown, including the **Self-Healing Watchdog** and **State Piggybacking** protocols, see:
**[ResonanceArchitecture.md](./ResonanceArchitecture.md)**

---

## Directory Structure

| Module | Description |
| :--- | :--- |
| **`resonance_core/`** | The central service hub. Handles ZMQ IPC, thread orchestration, and `libpd` execution. |
| **`soundcard/`** | Audio abstraction layer. Manages PortAudio streams, sine wave synthesis, and dynamic routing (HDMI/USB). |
| **`led_driver/`** | Serial communication bridge for the Raspberry Pi Pico LED controller. |
| **`puredata/`** | Legacy standalone UDP utility (now superseded by embedded `libpd` in the core). |
| **`resonance_sdk/`** | *[Deprecated]* Legacy C++ client wrapper. |

---

## Key Features

1. **Embedded libpd:** No external PureData process needed. Music is computed natively inside the core.
2. **Self-Healing Watchdog:** Autonomously detects and recovers from USB Soundcard or HDMI disconnects without crashing.
3. **Hardware Worker Isolation:** Offloads Serial I/O to a background thread to prevent audio glitches.
4. **State Piggybacking:** Every ZMQ reply includes the current musical state (note/symbol) to keep the UI in perfect sync.

---

## Building the Project

The project uses a unified CMake build system that automatically manages dependencies (ZeroMQ, PortAudio, nlohmann_json, libpd, etc.) via `FetchContent`.

### **Building**
```bash
make all
```
This will create a `build/` directory and compile all components.

---

## Configuration

1. **`master_symbols.json`**: Physical definitions of patterns (Logical Transducers 1-4).
2. **`system_config.json`**: Hardware wiring, device name discovery, and ZMQ endpoints.
