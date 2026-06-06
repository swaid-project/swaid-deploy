# SWAID: Synchronized Vibroacoustic & Interactive Display

SWAID is an interactive vibroacoustic system designed for experiencing and demonstrating **Chladni plate resonance patterns**. The system is composed of two primary modules coordinating in real-time:

1. **Human Interface (Python UI)**: A gesture-controlled front-end using PySide6 (Qt) and MediaPipe for hands-free interaction.
2. **Plate Resonance (C++ Core)**: A high-performance, multi-threaded hardware orchestrator that controls transducers, serial LEDs, and external musical synthesis.

---

## Architecture Overview

SWAID uses a **"Smart Client, Synchronized Core"** paradigm:
* The **Python UI** manages user states, interprets gesture tracking (hover/dwell selection), reads the UI database configuration, and monitors performance diagnostics.
* The **C++ Server** is an ultra-fast, low-latency execution node that interacts with hardware drivers (soundcard outputs, Pico LED strips, and PureData UDP ports) without holding high-level application state.

```
                    +-----------------------------+
                    |    Python UI Client (Qt)    |
                    |  - MediaPipe Hand Tracking  |
                    |  - 100ms Sync/Health Check  |
                    +--------------+--------------+
                                   |
                             ZMQ (REQ/REP)
                             /tmp/swaid.sock
                                   |
                    +--------------v--------------+
                    |    C++ Resonance Server     |
                    +-----+--------+--------+-----+
                          |        |        |
                    PortAudio    Serial    UDP
                    (Channels) (USB ACM) (3000/3001)
                          |        |        |
                    +-----v----+ +-v----+ +-v----+
                    |Transducer| |  RPi | | Pure |
                    | Speakers | | Pico | | Data |
                    +----------+ +------+ +------+
```

---

## Directory Structure

* **`human-interface/`**: Python application containing the tracking system (camera pipelines, gesture recognition) and dashboard UI.
* **`plate-resonance/`**: C++ CMake-based workspace.
  * **`resonance_core/`**: Central ZMQ orchestrator, watchdog manager, and thread controller.
  * **`soundcard/`**: PortAudio abstraction layer for real-time sine wave synthesis.
  * **`led_driver/`**: Serial communication bridge (Embedded SAL) for the LED controller.
  * **`puredata/`**: UDP transmitter component for sending MIDI note and mute/enable events to PureData.
* **`SERVER_SPECIFICATION.md`**: Architectural guidelines and ZMQ specification.
* **`CLIENT_SPECIFICATION.md`**: Front-end behavior and sync/diagnostics specification.

---

## Getting Started

### 1. Build and Run the C++ Core

Make sure you have CMake and standard build tools installed (along with PortAudio developmental files).

```bash
cd plate-resonance
mkdir -p build && cd build
cmake ..
make -j$(nproc)
./resonance_core/resonance_core
```

### 2. Run the Python Front-End

Install Python 3.10+ and setup the environment:

```bash
cd human-interface
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

*Note: Ensure your hand detection task file is placed in `models/hand_landmarker.task` as detailed in the `human-interface/README.md`.*

---

## System Communications & Safety

* **Watchdog Protection**: The server employs a 2-second dead man's switch. If the UI stops sending heartbeat pings for 2 seconds (e.g., UI crash or hang), the server automatically mutes all transducer channels and disables the PureData synth.
* **Audio Fade Safety**: Transducer outputs undergo a hardcoded fade-in/fade-out ramp (default 100ms) to avoid mechanical damage and zero-crossing speaker clicks.
* **Self-Healing Ports**: Transducers (PortAudio) and LEDs (Pico Serial) automatically attempt connection recovery in the background if disconnected.