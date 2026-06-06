# SWAID Plate Resonance Service

This directory contains the C++ backend service (the hardware orchestrator) for the SWAID (Synchronized Vibroacoustic & Interactive Display) project.

---

## Overview

The Plate Resonance service functions as a high-performance, real-time hardware manager. It handles real-time digital signal processing (DSP) for physical plate vibrations, forwards visual commands to serial LEDs, and sends network audio events to an external PureData synthesizer.

### **Architectural Paradigm: "Smart Client, Synchronized Core"**
- **Python UI (Smart Client):** The master controller containing the primary application state, assets, and user tracking.
- **C++ Core (Synchronized Hub):** A fast, low-overhead C++ process executing hardware interactions with high temporal precision.

For a detailed technical description of the architecture, including self-healing watchdog loops and the heartbeat dead man's switch, refer to:
**[ResonanceArchitecture.md](./ResonanceArchitecture.md)**

---

## Directory Structure

| Module | Description |
| :--- | :--- |
| **`resonance_core/`** | The central service manager. Hosts the ZeroMQ IPC socket (`/tmp/swaid.sock`), orchestrates the multi-threading loop, and dispatches commands. |
| **`soundcard/`** | Audio driver layer. Manages PortAudio device detection, multichan outputs, and real-time sine wave synthesis. |
| **`led_driver/`** | Serial communications layer (Embedded SAL) for controlling NeoPixel strips on a Raspberry Pi Pico. |
| **`puredata/`** | UDP transmission client library sending FUDI formatted note triggers to port 3000 and enable/disable events to port 3001. |

---

## Key Hardware Features

1. **UDP PureData Communications**: Sends note triggers to port 3000. PureData audio is initialized to disabled on boot (the server transmits a `"0"` to port 3001). The first trigger enables it (sending `"1"` to port 3001).
2. **Real-time Sine Synthesis**: Transducer vibrations are generated dynamically using PortAudio. Outgoing signals undergo a 100ms fade-in/fade-out envelope to protect the mechanical coils and avoid clicking artifacts.
3. **Pico LED Serial Offloading**: Serial writes to the Pico LED controller are executed in a dedicated background worker queue, preventing port blocking from stalling the real-time audio thread.
4. **Self-Healing Diagnostics**: The server monitors serial ports and PortAudio streams in real-time. If connection drops, it sets diagnostic flags to `0` and attempts reconnection in the background.

---

## Building the Project

The build utilizes CMake and leverages `FetchContent` to download and build ZeroMQ, PortAudio, and `nlohmann_json` dependencies automatically.

### Build commands:
```bash
# Run the Makefile wrapper from this directory or root
make all
```

The output executable is compiled into:
`build/resonance_core/resonance_core`
